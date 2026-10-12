/*
 * G1 BusLinker USB protocol probe for HX-30HM.
 *
 * Four of the five verbs are deliberately read-only: one single-cast PING, one
 * present-position READ, a read-only diagnostic register dump, and a two-byte
 * aligned sweep of the whole register map, all through a BusLinker V3.0
 * attached to the PS USB host.
 *
 * The fifth verb, write-reg, is the only path in this program that writes to a
 * servo.  It is fenced by a three-address whitelist (0x09 minimum angle limit,
 * 0x0B maximum angle limit, 0x37 write lock), requires an explicit
 * --confirm-write, is single-cast only, changes exactly one register per
 * invocation, and reads the register back before and after.  It never emits
 * ACTION, SYNC_WRITE, RESET, broadcast-ID, torque, mode, speed or position
 * commands.  The read verbs stay read-only and reject write options.
 *
 * The program proves USB enumeration, 1 Mbps 8N1 transport, and response
 * packet validation.  PL servo_tx_en remains disabled throughout this path.
 *
 * Why the dump exists: the PL read whitelist only exposes 0x38 and 0x28, so a
 * servo that refuses a goal cannot be interrogated through the PL at all.
 * This path bypasses the PL entirely and reads the servo's own configuration
 * (mode, protection mask, torque limit, deadband, position correction) so a
 * mis-configured or defective unit can be compared against a known-good one.
 * It stays strictly read-only; adding reads cannot command motion.
 *
 * A servo that returns "angle" status for any wide goal but accepts goals near
 * one value behaves as if an internal allowed-position window rejected the
 * target before motion.  No documented HX-30HM register holds such a window,
 * but the V3.7 sheet jumps straight from 0x08 to 0x0D and from 0x1C to 0x1F,
 * so the sweep reads every byte of 0x00..0x47 - including those undocumented
 * gaps - instead of guessing which block to trust.
 *
 * The sweep reads TWO bytes per READ, aligned to even addresses.  A measured
 * HX-30HM does not answer every single-byte READ faithfully: reading the high
 * byte of a 16-bit field on its own returns a fixed 0xD0 while the same byte
 * is correct inside a multi-byte READ (0x11 alone gives 0xD0, but a 2-byte
 * READ at 0x10 gives [E8 03]).  Two-byte blocks therefore cover all 16-bit
 * fields correctly, and never print a fabricated leading byte.
 */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <fcntl.h>
#include <sys/select.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#define HX_FRAME_HEADER 0xffU
#define HX_INST_PING 0x01U
#define HX_INST_READ 0x02U
#define HX_INST_WRITE 0x03U
#define HX_ADDR_PRESENT_POSITION 0x38U
#define HX_POSITION_BYTES 2U
#define HX_MAX_RESPONSE_LENGTH 32U
#define HX_MAX_READ_BYTES 8U
#define HX_MAX_WRITE_BYTES 2U
#define HX_BAUD 1000000U
#define UART_FRAME_BITS 10U
/* 双字节扫描的上界：HX-30HM 已文档化的最高地址是 0x45，取到偶地址 0x46 即可
 * 覆盖 0x46..0x47。 */
#define HX_SWEEP_LAST 0x46U
#define HX_SWEEP_STEP 2U

typedef enum {
  REQUEST_PING,
  REQUEST_READ_POSITION,
  REQUEST_DUMP,
  REQUEST_SWEEP,
  REQUEST_WRITE_REG,
} request_kind;

/* 可写白名单。写通路只认这三个地址，永远不会变成通用舵机写入器：
 *   0x09 最小角度限制（16 位小端，NVS）
 *   0x0B 最大角度限制（16 位小端，NVS）
 *   0x37 写入锁（1 字节，SRAM）：写 1 打开锁 -> 其后对 NVS 的写入掉电不保存；
 *        写 0 关闭锁 -> NVS 写入掉电保存。
 * 出厂值 0x09=0、0x0B=4095；实测 ID 5 被改成 0x09=1926、0x0B=2049。 */
typedef struct {
  uint8_t addr;
  uint8_t length;
  const char *name;
} write_target;

static const write_target write_table[] = {
  {0x09U, 2U, "angle_limit_min"},
  {0x0bU, 2U, "angle_limit_max"},
  {0x37U, 1U, "write_lock"},
};

/* HX-30HM V3.7 register table, read-only subset.  Each entry is one READ of a
 * contiguous block no longer than HX_MAX_READ_BYTES.  Addresses never listed
 * here are never touched. */
typedef struct {
  uint8_t addr;
  uint8_t length;
  uint8_t scalar;  /* 1 = 该块是单一数值字段，额外打印小端 value */
  const char *name;
} reg_probe;

static const reg_probe reg_table[] = {
  {0x00U, 2U, 0U, "firmware_ver"},
  {0x03U, 2U, 0U, "servo_ver"},
  {0x05U, 1U, 1U, "servo_id"},
  {0x06U, 1U, 1U, "baud_code"},
  {0x08U, 1U, 1U, "reply_level"},
  /* V3.7 表从 0x08 直接跳到 0x0D。Feetech 系固件在同一空档放"最小/最大
   * 角度限制"两个 16 位字段，而"目标越界即报角度错误"正是待验证的机制，
   * 所以这个空档必须实测，不能假定它不存在。 */
  {0x09U, 4U, 0U, "gap_09_0c"},
  {0x0dU, 3U, 0U, "temp_volt_thr"},
  {0x10U, 2U, 1U, "torque_limit"},
  {0x13U, 2U, 0U, "protect_mask"},
  {0x15U, 3U, 0U, "pos_loop_pid"},
  {0x18U, 2U, 1U, "start_force"},
  {0x1aU, 2U, 0U, "deadband_cw_ccw"},
  {0x1cU, 2U, 1U, "overcurrent_thr"},
  {0x1dU, 2U, 0U, "gap_1d_1e"},
  {0x1fU, 2U, 1U, "position_offset"},
  {0x21U, 1U, 1U, "run_mode"},
  {0x22U, 6U, 0U, "overload_speed_pid"},
  {0x28U, 4U, 0U, "torque_accel_goal"},
  {0x2cU, 4U, 0U, "pwm_speed_run_speed"},
  {0x37U, 1U, 1U, "lock_flag"},
  {0x38U, 4U, 0U, "position_speed"},
  {0x3cU, 2U, 0U, "load"},
  {0x3eU, 5U, 0U, "volt_temp_flags"},
  {0x41U, 1U, 1U, "servo_status"},
  {0x42U, 1U, 1U, "moving_flag"},
  {0x45U, 2U, 1U, "current"},
};

typedef struct {
  const char *device;
  uint8_t id;
  unsigned timeout_ms;
  request_kind kind;
  unsigned write_addr;      /* --addr，仅 write-reg 使用 */
  unsigned write_value;     /* --value */
  unsigned addr_seen;       /* --value 允许为 0，必须另记"是否出现过" */
  unsigned value_seen;
  unsigned confirmed;       /* --confirm-write */
} config_t;

static uint64_t monotonic_ms(void) {
  struct timespec ts;
  (void)clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000U + (uint64_t)ts.tv_nsec / 1000000U;
}

static uint8_t checksum(const uint8_t *body, size_t length) {
  uint8_t sum = 0U;
  size_t index;
  for (index = 0U; index < length; ++index) sum = (uint8_t)(sum + body[index]);
  return (uint8_t)~sum;
}

static void print_usage(const char *program) {
  fprintf(stderr,
          "usage: %s --device /dev/ttyACM<N>|/dev/ttyUSB<N> --id 1..253 "
          "[--timeout-ms 1..1000] <ping|read-position|dump|sweep>\n"
          "       %s --device ... --id 1..253 --addr 0x09|0x0B|0x37 "
          "--value N --confirm-write write-reg\n"
          "read verbs: serial format fixed at 1000000-8N1, READ only, never write.\n"
          "  dump  读取 HX-30HM 已文档化配置寄存器；绝不写任何寄存器。\n"
          "  sweep 按偶地址双字节读取 0x00..0x47 全映射（含文档跳过的空档），\n"
          "        用于与正常轴对比；同样只读。\n"
          "write-reg: 唯一会写舵机的动词，白名单仅 0x09 最小角度限制、\n"
          "  0x0B 最大角度限制、0x37 写入锁；必须显式 --confirm-write，\n"
          "  只单播（不接受广播 ID）；写入前后各读回一次做对照。\n",
          program, program);
}

static int parse_uint(const char *text, unsigned lower, unsigned upper, unsigned *value) {
  char *end = NULL;
  unsigned long parsed;
  errno = 0;
  parsed = strtoul(text, &end, 10);
  if (errno != 0 || end == text || *end != '\0' || parsed < lower || parsed > upper) return -1;
  *value = (unsigned)parsed;
  return 0;
}

/* 地址接受 0x 前缀的十六进制，与寄存器表、XLS 和现场输出保持一致。 */
static int parse_addr(const char *text, unsigned *value) {
  char *end = NULL;
  unsigned long parsed;
  errno = 0;
  parsed = strtoul(text, &end, 0);
  if (errno != 0 || end == text || *end != '\0' || parsed > 0xffU) return -1;
  *value = (unsigned)parsed;
  return 0;
}

static const write_target *find_write_target(unsigned addr) {
  size_t index;
  for (index = 0U; index < sizeof(write_table) / sizeof(write_table[0]); ++index)
    if (write_table[index].addr == (uint8_t)addr) return &write_table[index];
  return NULL;
}

static int parse_args(int argc, char **argv, config_t *config) {
  int index;
  int action_set = 0;
  unsigned id = 0U;
  config->device = NULL;
  config->id = 0U;
  config->timeout_ms = 100U;
  config->kind = REQUEST_PING;
  config->write_addr = 0U;
  config->write_value = 0U;
  config->addr_seen = 0U;
  config->value_seen = 0U;
  config->confirmed = 0U;

  for (index = 1; index < argc; ++index) {
    if (strcmp(argv[index], "--device") == 0 && index + 1 < argc) {
      config->device = argv[++index];
    } else if (strcmp(argv[index], "--id") == 0 && index + 1 < argc) {
      if (parse_uint(argv[++index], 1U, 253U, &id) != 0) {
        fputs("ERR invalid_id; use single-cast ID 1..253\n", stderr);
        return -1;
      }
      config->id = (uint8_t)id;
    } else if (strcmp(argv[index], "--timeout-ms") == 0 && index + 1 < argc) {
      if (parse_uint(argv[++index], 1U, 1000U, &config->timeout_ms) != 0) {
        fputs("ERR invalid_timeout_ms\n", stderr);
        return -1;
      }
    } else if (strcmp(argv[index], "--addr") == 0 && index + 1 < argc) {
      if (parse_addr(argv[++index], &config->write_addr) != 0) {
        fputs("ERR invalid_addr; use 0xNN\n", stderr);
        return -1;
      }
      config->addr_seen = 1U;
    } else if (strcmp(argv[index], "--value") == 0 && index + 1 < argc) {
      if (parse_uint(argv[++index], 0U, 0xffffU, &config->write_value) != 0) {
        fputs("ERR invalid_value; use 0..65535\n", stderr);
        return -1;
      }
      config->value_seen = 1U;
    } else if (strcmp(argv[index], "--confirm-write") == 0) {
      config->confirmed = 1U;
    } else if (strcmp(argv[index], "ping") == 0) {
      config->kind = REQUEST_PING;
      action_set = 1;
    } else if (strcmp(argv[index], "read-position") == 0) {
      config->kind = REQUEST_READ_POSITION;
      action_set = 1;
    } else if (strcmp(argv[index], "dump") == 0) {
      config->kind = REQUEST_DUMP;
      action_set = 1;
    } else if (strcmp(argv[index], "sweep") == 0) {
      config->kind = REQUEST_SWEEP;
      action_set = 1;
    } else if (strcmp(argv[index], "write-reg") == 0) {
      config->kind = REQUEST_WRITE_REG;
      action_set = 1;
    } else {
      print_usage(argv[0]);
      return -1;
    }
  }
  if (config->device == NULL || config->id == 0U || !action_set) {
    print_usage(argv[0]);
    return -1;
  }
  /* 写动词必须显式确认，且地址与值都必须由操作者给出；读动词不接受这些参数，
   * 避免有人以为 ping/dump 也能顺手写寄存器。 */
  if (config->kind == REQUEST_WRITE_REG) {
    if (!config->confirmed) {
      fputs("ERR write_requires_confirm_write; this verb changes servo NVS\n", stderr);
      return -1;
    }
    if (!config->addr_seen || !config->value_seen) {
      fputs("ERR write_requires_addr_and_value\n", stderr);
      return -1;
    }
  } else if (config->addr_seen || config->value_seen || config->confirmed) {
    fputs("ERR write_options_only_valid_with_write_reg\n", stderr);
    return -1;
  }
  return 0;
}

static int open_buslinker(const config_t *config) {
  int fd;
  struct termios tio;

#ifndef B1000000
  (void)config;
  fputs("ERR target_termios_has_no_B1000000\n", stderr);
  return -1;
#else
  fd = open(config->device, O_RDWR | O_NOCTTY);
  if (fd < 0) {
    fprintf(stderr, "ERR open_failed %s: %s\n", config->device, strerror(errno));
    return -1;
  }
  if (tcgetattr(fd, &tio) != 0) {
    fprintf(stderr, "ERR tcgetattr: %s\n", strerror(errno));
    (void)close(fd);
    return -1;
  }
  cfmakeraw(&tio);
  tio.c_cflag &= (tcflag_t)~(PARENB | CSTOPB | CRTSCTS);
  tio.c_cflag |= CLOCAL | CREAD | CS8;
  tio.c_iflag &= (tcflag_t)~(IXON | IXOFF | IXANY);
  tio.c_cc[VMIN] = 0;
  tio.c_cc[VTIME] = 0;
  if (cfsetispeed(&tio, B1000000) != 0 || cfsetospeed(&tio, B1000000) != 0 ||
      tcsetattr(fd, TCSANOW, &tio) != 0) {
    fprintf(stderr, "ERR serial_config: %s\n", strerror(errno));
    (void)close(fd);
    return -1;
  }
  (void)tcflush(fd, TCIOFLUSH);
  return fd;
#endif
}

static int write_frame(int fd, const uint8_t *frame, size_t length) {
  size_t sent = 0U;
  while (sent < length) {
    ssize_t written = write(fd, frame + sent, length - sent);
    if (written < 0) {
      if (errno == EINTR) continue;
      fprintf(stderr, "ERR write: %s\n", strerror(errno));
      return -1;
    }
    sent += (size_t)written;
  }
  if (tcdrain(fd) != 0) {
    fprintf(stderr, "ERR tcdrain: %s\n", strerror(errno));
    return -1;
  }
  return 0;
}

static int read_one_until(int fd, uint64_t deadline_ms, uint8_t *byte) {
  while (monotonic_ms() < deadline_ms) {
    uint64_t remaining_ms = deadline_ms - monotonic_ms();
    struct timeval wait;
    fd_set readable;
    ssize_t got;
    int ready;
    FD_ZERO(&readable);
    FD_SET(fd, &readable);
    wait.tv_sec = (time_t)(remaining_ms / 1000U);
    wait.tv_usec = (suseconds_t)((remaining_ms % 1000U) * 1000U);
    ready = select(fd + 1, &readable, NULL, NULL, &wait);
    if (ready < 0 && errno == EINTR) continue;
    if (ready < 0) {
      fprintf(stderr, "ERR select: %s\n", strerror(errno));
      return -1;
    }
    if (ready == 0) break;
    got = read(fd, byte, 1U);
    if (got == 1) return 1;
    if (got < 0 && errno != EINTR) {
      fprintf(stderr, "ERR read: %s\n", strerror(errno));
      return -1;
    }
  }
  return 0;
}

/* Returns 0 for a valid reply, -1 for a transport/protocol failure. */
static int read_response(int fd, uint8_t expected_id, unsigned timeout_ms,
                         uint8_t *error_code, uint8_t *parameters, size_t *parameter_count) {
  enum { WAIT_HEADER0, WAIT_HEADER1, WAIT_ID, WAIT_LENGTH, WAIT_BODY } state = WAIT_HEADER0;
  uint8_t body[2U + HX_MAX_RESPONSE_LENGTH];
  uint8_t byte = 0U;
  uint8_t length = 0U;
  size_t body_count = 0U;
  uint64_t deadline_ms = monotonic_ms() + timeout_ms;

  while (monotonic_ms() < deadline_ms) {
    int received = read_one_until(fd, deadline_ms, &byte);
    if (received <= 0) break;
    switch (state) {
      case WAIT_HEADER0:
        state = (byte == HX_FRAME_HEADER) ? WAIT_HEADER1 : WAIT_HEADER0;
        break;
      case WAIT_HEADER1:
        state = (byte == HX_FRAME_HEADER) ? WAIT_ID : WAIT_HEADER0;
        break;
      case WAIT_ID:
        if (byte != expected_id) {
          state = (byte == HX_FRAME_HEADER) ? WAIT_HEADER1 : WAIT_HEADER0;
          break;
        }
        body[0] = byte;
        state = WAIT_LENGTH;
        break;
      case WAIT_LENGTH:
        if (byte < 2U || byte > HX_MAX_RESPONSE_LENGTH) {
          fputs("ERR malformed_response_length\n", stderr);
          return -1;
        }
        length = byte;
        body[1] = byte;
        body_count = 0U;
        state = WAIT_BODY;
        break;
      case WAIT_BODY:
        body[2U + body_count++] = byte;
        if (body_count == length) {
          if (checksum(body, 1U + length) != body[1U + length]) {
            fputs("ERR response_checksum\n", stderr);
            return -1;
          }
          *error_code = body[2];
          *parameter_count = (size_t)length - 2U;
          memcpy(parameters, &body[3], *parameter_count);
          return 0;
        }
        break;
      default:
        return -1;
    }
  }
  fputs("ERR response_timeout\n", stderr);
  return -1;
}

static void print_hex(const char *prefix, const uint8_t *data, size_t length) {
  size_t index;
  fputs(prefix, stdout);
  for (index = 0U; index < length; ++index) printf("%s%02X", index == 0U ? "" : " ", data[index]);
  putchar('\n');
}

static void format_hex(char *out, size_t out_size, const uint8_t *data, size_t length) {
  size_t pos = 0U;
  size_t index;
  out[0] = '\0';
  for (index = 0U; index < length; ++index) {
    int written = snprintf(out + pos, out_size - pos, "%s%02X",
                           index == 0U ? "" : " ", data[index]);
    if (written < 0 || (size_t)written >= out_size - pos) break;
    pos += (size_t)written;
  }
}

/* One single-cast READ of `length` bytes starting at `addr`. */
static size_t build_read_frame(uint8_t *frame, uint8_t id, uint8_t addr, uint8_t length) {
  frame[0] = HX_FRAME_HEADER;
  frame[1] = HX_FRAME_HEADER;
  frame[2] = id;
  frame[3] = 4U;
  frame[4] = HX_INST_READ;
  frame[5] = addr;
  frame[6] = length;
  frame[7] = checksum(&frame[2], 5U);
  return 8U;
}

/* WRITE 帧：FF FF ID LEN 03 ADDR DATA... CS。
 * 参数 = ADDR + length 个数据字节，LEN = 参数字节数 + 2，校验覆盖 ID..最后一个参数。
 * 长度 2 时共 9 字节（LEN=5）；长度 1 时共 8 字节（LEN=4）。 */
static size_t build_write_frame(uint8_t *frame, uint8_t id, uint8_t addr,
                                unsigned value, uint8_t length) {
  uint8_t param_bytes = (uint8_t)(1U + length);
  uint8_t index;
  frame[0] = HX_FRAME_HEADER;
  frame[1] = HX_FRAME_HEADER;
  frame[2] = id;
  frame[3] = (uint8_t)(param_bytes + 2U);
  frame[4] = HX_INST_WRITE;
  frame[5] = addr;
  for (index = 0U; index < length; ++index)
    frame[6U + index] = (uint8_t)(value >> (8U * index));
  frame[6U + length] = checksum(&frame[2], (size_t)param_bytes + 3U);
  return (size_t)(7U + length);
}

/* 读回一个白名单地址的当前值。返回 0 表示拿到 length 个字节。 */
static int read_back_value(int fd, const config_t *config, const write_target *target,
                           uint8_t *parameters, size_t *parameter_count,
                           uint8_t *response_error, unsigned *value) {
  uint8_t frame[8];
  size_t frame_length = build_read_frame(frame, config->id, target->addr, target->length);
  size_t index;
  *response_error = 0U;
  *value = 0U;
  if (write_frame(fd, frame, frame_length) != 0) return -1;
  if (read_response(fd, config->id, config->timeout_ms, response_error,
                    parameters, parameter_count) != 0) return -1;
  if (*parameter_count != (size_t)target->length) return -1;
  for (index = 0U; index < *parameter_count; ++index)
    *value |= (unsigned)parameters[index] << (8U * index);
  return 0;
}

static const char *request_name(request_kind kind) {
  switch (kind) {
    case REQUEST_PING: return "PING";
    case REQUEST_READ_POSITION: return "READ_PRESENT_POSITION";
    case REQUEST_SWEEP: return "READ_REGISTER_SWEEP";
    case REQUEST_WRITE_REG: return "WRITE_REGISTER";
    default: return "READ_REGISTER_DUMP";
  }
}

int main(int argc, char **argv) {
  config_t config;
  uint8_t frame[8];
  uint8_t response_error = 0U;
  uint8_t parameters[HX_MAX_RESPONSE_LENGTH - 2U];
  size_t parameter_count = 0U;
  size_t frame_length;
  int fd;

  if (parse_args(argc, argv, &config) != 0) return EXIT_FAILURE;
  fd = open_buslinker(&config);
  if (fd < 0) return EXIT_FAILURE;

  printf("RTCS_BUSLINKER_G1_START device=%s baud=%u format=8N1 flow_control=none "
         "theoretical_bytes_per_second=%u id=%u command=%s\n",
         config.device, HX_BAUD, HX_BAUD / UART_FRAME_BITS, config.id,
         request_name(config.kind));

  /* Read-only configuration snapshot: one READ per table entry.  Nothing in
   * this path can command motion, torque, mode or speed. */
  if (config.kind == REQUEST_DUMP) {
    size_t entry;
    unsigned probes = 0U;
    unsigned failures = 0U;
    char hexbuf[HX_MAX_READ_BYTES * 3U + 1U];
    for (entry = 0U; entry < sizeof(reg_table) / sizeof(reg_table[0]); ++entry) {
      const reg_probe *probe = &reg_table[entry];
      unsigned value = 0U;
      size_t byte_index;
      probes++;
      /* 每一探针从零开始：超时没有收到状态字节，不能把上一条的 ERROR 当
       * 成本条的读数继续往下传。 */
      response_error = 0U;
      frame_length = build_read_frame(frame, config.id, probe->addr, probe->length);
      if (write_frame(fd, frame, frame_length) != 0 ||
          read_response(fd, config.id, config.timeout_ms, &response_error,
                        parameters, &parameter_count) != 0 ||
          parameter_count != (size_t)probe->length) {
        failures++;
        printf("reg name=%-20s addr=0x%02X len=%u raw=[UNAVAILABLE]"
               " servo_error=UNAVAILABLE\n",
               probe->name, probe->addr, probe->length);
        fflush(stdout);
        continue;
      }
      format_hex(hexbuf, sizeof(hexbuf), parameters, parameter_count);
      /* 只有单一数值字段才额外打印小端 value：多字段块拼出来的数字没有
       * 意义，印它只会误导读数。 */
      if (probe->scalar) {
        for (byte_index = 0U; byte_index < parameter_count; ++byte_index)
          value |= (unsigned)parameters[byte_index] << (8U * byte_index);
        printf("reg name=%-20s addr=0x%02X len=%u raw=[%s] servo_error=0x%02X value=%u\n",
               probe->name, probe->addr, probe->length, hexbuf, response_error, value);
      } else {
        printf("reg name=%-20s addr=0x%02X len=%u raw=[%s] servo_error=0x%02X\n",
               probe->name, probe->addr, probe->length, hexbuf, response_error);
      }
      fflush(stdout);
    }
    printf("RTCS_BUSLINKER_G1_DUMP probes=%u ok=%u failed=%u read_only=1\n",
           probes, probes - failures, failures);
    (void)close(fd);
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
  }

  /* 双字节扫描 0x00..0x47（偶地址对齐）。一个地址一次 READ，互不牵连：某个
   * 地址不存在只让那一行显示 UNAVAILABLE，不会隐藏相邻地址。用双字节是因为
   * 实测该舵机对"16 位字段高字节的单字节读取"会返回固定的 0xD0 伪值。
   * 这条路径同样只发 READ，绝不写。 */
  if (config.kind == REQUEST_SWEEP) {
    unsigned addr;
    unsigned ok = 0U;
    unsigned failed = 0U;
    for (addr = 0U; addr <= HX_SWEEP_LAST; addr += HX_SWEEP_STEP) {
      response_error = 0U;
      frame_length = build_read_frame(frame, config.id, (uint8_t)addr,
                                      (uint8_t)HX_SWEEP_STEP);
      if (write_frame(fd, frame, frame_length) != 0 ||
          read_response(fd, config.id, config.timeout_ms, &response_error,
                        parameters, &parameter_count) != 0 ||
          parameter_count != (size_t)HX_SWEEP_STEP) {
        failed++;
        printf("word addr=0x%02X raw=UNAVAILABLE\n", addr);
      } else {
        ok++;
        printf("word addr=0x%02X raw=[%02X %02X] servo_error=0x%02X\n",
               addr, parameters[0], parameters[1], response_error);
      }
      fflush(stdout);
    }
    printf("RTCS_BUSLINKER_G1_SWEEP words=%u bytes=%u ok=%u failed=%u read_only=1\n",
           (unsigned)((HX_SWEEP_LAST / HX_SWEEP_STEP) + 1U),
           (unsigned)(HX_SWEEP_LAST + HX_SWEEP_STEP), ok, failed);
    (void)close(fd);
    return failed == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
  }

  /* 唯一会写舵机的路径。四条硬约束：
   *   1. 地址必须在 write_table 白名单内（0x09 / 0x0B / 0x37）；
   *   2. 必须显式 --confirm-write（解析阶段已检查）；
   *   3. 只单播：--id 已被限制为 1..253，构造广播 ID 254 不可能；
   *   4. 一次调用只改一个寄存器，写入前后各读回一次，不重试、不序列化。
   * 注意 0x09/0x0B 是 NVS：0x37 写入锁=0 时改动掉电保存；把锁置 1 再写，
   * 则改动立即生效但掉电丢弃，可用于可回退的试探。 */
  if (config.kind == REQUEST_WRITE_REG) {
    const write_target *target = find_write_target(config.write_addr);
    uint8_t tx_frame[8U + HX_MAX_WRITE_BYTES];
    size_t tx_frame_length;
    unsigned before = 0U, after = 0U;
    int have_before, have_after;
    uint8_t ack_error;

    if (target == NULL) {
      fprintf(stderr, "ERR address_not_in_write_whitelist addr=0x%02X"
                      " allowed=0x09,0x0B,0x37\n", config.write_addr);
      (void)close(fd);
      return EXIT_FAILURE;
    }
    if (config.write_value > (unsigned)(target->length == 1U ? 0xffU : 0xffffU)) {
      fprintf(stderr, "ERR value_out_of_range name=%s max=%u\n", target->name,
              target->length == 1U ? 255U : 65535U);
      (void)close(fd);
      return EXIT_FAILURE;
    }

    have_before = read_back_value(fd, &config, target, parameters,
                                  &parameter_count, &response_error, &before) == 0;
    if (!have_before)
      fputs("WARN pre_write_read_failed; 仍按操作者的显式请求执行写入\n", stderr);

    printf("RTCS_BUSLINKER_G1_WRITE_TARGET device=%s id=%u name=%s addr=0x%02X"
           " length=%u requested=%u before=",
           config.device, config.id, target->name, target->addr, target->length,
           config.write_value);
    if (have_before) printf("%u", before); else printf("UNAVAILABLE");
    printf(" persistence=%s\n",
           config.write_addr == 0x37U ? "SRAM_volatile"
                                      : "NVS_saved_while_lock_is_zero");

    tx_frame_length = build_write_frame(tx_frame, config.id, target->addr,
                                        config.write_value, target->length);
    print_hex("TX ", tx_frame, tx_frame_length);

    ack_error = 0U;
    response_error = 0U;
    if (write_frame(fd, tx_frame, tx_frame_length) != 0 ||
        read_response(fd, config.id, config.timeout_ms, &response_error,
                      parameters, &parameter_count) != 0 ||
        parameter_count != 0U) {
      fputs("ERR write_ack_failed; 舵机未确认本次写入\n", stderr);
      (void)close(fd);
      return EXIT_FAILURE;
    }
    ack_error = response_error;

    have_after = read_back_value(fd, &config, target, parameters,
                                 &parameter_count, &response_error, &after) == 0;
    printf("RTCS_BUSLINKER_G1_WRITE name=%s addr=0x%02X length=%u requested=%u"
           " before=", target->name, target->addr, target->length, config.write_value);
    if (have_before) printf("%u", before); else printf("UNAVAILABLE");
    printf(" after=");
    if (have_after) printf("%u", after); else printf("UNAVAILABLE");
    printf(" write_ack_error=0x%02X value_matches=%u\n", ack_error,
           (have_after && after == config.write_value) ? 1U : 0U);

    if (config.write_addr != 0x37U)
      fputs("HINT 0x09/0x0B 为 NVS。若 0x37 写入锁=0，本次改动掉电保存；"
            "若要可回退，先用 --addr 0x37 --value 1 打开写入锁再写，"
            "断电即可恢复原值。\n", stderr);
    (void)close(fd);
    return (ack_error == 0U && have_after && after == config.write_value)
               ? EXIT_SUCCESS : EXIT_FAILURE;
  }

  frame[0] = HX_FRAME_HEADER;
  frame[1] = HX_FRAME_HEADER;
  frame[2] = config.id;
  if (config.kind == REQUEST_PING) {
    frame[3] = 2U;
    frame[4] = HX_INST_PING;
    frame[5] = checksum(&frame[2], 3U);
    frame_length = 6U;
  } else {
    frame_length = build_read_frame(frame, config.id, HX_ADDR_PRESENT_POSITION,
                                    HX_POSITION_BYTES);
  }
  print_hex("TX ", frame, frame_length);
  if (write_frame(fd, frame, frame_length) != 0 ||
      read_response(fd, config.id, config.timeout_ms, &response_error, parameters, &parameter_count) != 0) {
    (void)close(fd);
    return EXIT_FAILURE;
  }

  printf("RTCS_BUSLINKER_G1_REPLY id=%u servo_error=0x%02X payload_bytes=%zu\n",
         config.id, response_error, parameter_count);
  if (config.kind == REQUEST_PING) {
    if (parameter_count != 0U) {
      fputs("ERR ping_payload_length\n", stderr);
      (void)close(fd);
      return EXIT_FAILURE;
    }
  } else {
    uint16_t position;
    if (parameter_count != HX_POSITION_BYTES) {
      fputs("ERR position_payload_length\n", stderr);
      (void)close(fd);
      return EXIT_FAILURE;
    }
    position = (uint16_t)parameters[0] | ((uint16_t)parameters[1] << 8U);
    printf("position_raw=%u position_degrees=%.3f\n", position, (double)position * 360.0 / 4095.0);
  }
  if (response_error != 0U) {
    fputs("ERR servo_reported_fault\n", stderr);
    (void)close(fd);
    return EXIT_FAILURE;
  }
  puts("RTCS_BUSLINKER_G1_OK");
  (void)close(fd);
  return EXIT_SUCCESS;
}
