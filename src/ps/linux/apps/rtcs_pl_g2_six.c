/*
 * RTCS 六轴命令行（PS/Linux 用户态）—— ABI 0x5254000E
 *
 * 这个程序本身不拼任何一帧十六进制。它只做三件事：
 *   1) mmap UIO 暴露的 AXI4-Lite 寄存器组（复位后先核对 ABI）；
 *   2) 往寄存器里写"描述符"并提交命令字，交由 PL 的状态机执行；
 *   3) 轮询 PL 的结果寄存器，把结果翻译成人能读的判定。
 * 真正的组帧、总线时序、发后反馈轮询、限位门禁全在 PL 里。
 *
 * 两条硬边界：
 *   * 会发运动帧的命令必须显式 --execute，且全部通过 PL 的 G2 状态机；
 *   * 只读命令（limits / diagnose / torque-status）绝不提交运动命令字，
 *     只走 G1 白名单路径或读 PL 的编译期常量。
 *
 * ───────────────────────── 六条命令的执行链路 ─────────────────────────
 *
 * limits（只读）
 *   PS：读 CAL_MASK 确认该轴已标定 -> 写 LIMIT_ID 选轴 -> 读回 LIMIT_MIN/MAX/
 *       REFERENCE/SPEED_MAX 并做合法性检查（lo<=hi<=65535、speed_max>0）。
 *   PL：这些是综合进 bitstream 的编译期常量，不是运行时写入的。
 *   收尾：全部合法才打印 RTCS_PL_G2_SIX_LIMITS_OK，否则报错退出。
 *
 * diagnose（只读）
 *   PS：逐轴走 G1 白名单的 READ(0x38) 位置读取，逐轴解释故障。
 *   PL：G1 路径只放行 PING / READ / READ_TORQUE / TORQUE_OFF，运动操作码被拒。
 *   收尾：任一轴有问题则以非零退出，末行给出 issues 计数；只读，write_sent=0。
 *
 * torque-status（只读）
 *   PS：走 G1 白名单的 READ_TORQUE(0x28)，取回扭矩开关的低字节。
 *   PL：与 diagnose 同一条 G1 只读路径。
 *
 * calibrate-step（会发帧，需 --execute，只对单轴）
 *   PS 先做功能性发前 READ：必须知道起点才能算出 goal = pos + delta。
 *   PL：CAL_READ_START（读该轴当前位置）→ 查限位算出目标 → WRITE_START
 *       （单播 WRITE，speed=500/time=10）→ 反馈轮询，每条样本写进 128 深日志
 *       （溢出报 fault 14）→ 连续三次落在容差内才 DONE。
 *   PS 收尾：把日志逐条打印成 calibrate-start / sample= / calibrate-final。
 *
 * move-six（会发帧，需 --execute，必须给满六轴）
 *   PS 发前：要求 CAL_MASK==0x3F；逐轴读限位并校验目标与原始速度；
 *            写 TARGET0+4n、PARAM0+4n、逐轴 TOLERANCE、OBSERVE。
 *   PL：CHECK_GUARD（描述符守卫，查限位/标定/禁发/截止时间/总线占用）→
 *       WRITE_START 发广播 SYNC_WRITE（ID=0xFE，一帧同时驱动六轴）→
 *       六轴轮流 READ 位置 → 连续三轮全轴到位才 DONE。
 *   注意：广播没有协议 ACK，所以 unicast_ack 恒为 NOT_APPLICABLE_BROADCAST。
 *
 * stop（会发帧，需 --execute）
 *   PS 发前：保留功能性发前 READ，必须知道当前位置才能原地保持。
 *   PL：STOP_CLEAR → 读六轴当前位置 → 广播 SYNC_WRITE（speed=1500）原地保持。
 *   语义提醒：这是"读后保持"，不是断力；断力请用 rtcs-pl-g2 的 release。
 *
 * 另外：任何命令执行期间收到 SIGINT，不直接退出，而是重装截止时间后再提交
 * 一次 0x47320005（软件急停请求），随后按失败返回。
 * ──────────────────────────────────────────────────────────────────────
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include "rtcs_servo_diag.h"

/* ── 寄存器映射（AXI4-Lite 基址 0x43C00000 起 64 KiB） ───────────────── */
enum {
  MAP_SIZE = 65536,
  ABI     = 0x5254000e,   /* 当前源码 ABI；0D 板子可兼容运行（见 ABI_0D） */
  ABI_0D  = 0x5254000d,

  ID        = 0x00,       /* [RO] ABI 标识，复位值即契约 */
  TICKS_LO  = 0x14,       /* [RO] 自由计数器低 32 位 */
  TICKS_HI  = 0x18,       /* [RO] 自由计数器高 32 位 */

  TARGET0   = 0x20,       /* 六轴目标，每轴 +4 */

  G1_ID     = 0x50,       /* G1 事务：目标舵机 ID */
  G1_OP     = 0x54,       /* G1 事务：操作码（1 PING，2 READ 位置，9 卸力，11 读扭矩开关） */
  G1_CMD    = 0x58,       /* G1 事务：写 1 启动、写 2 清除 */
  G1_STATUS = 0x5c,       /* G1 状态：bit0 忙、bit1 完成、bit2 错误、bit3 物理禁发 */
  G1_RESULT = 0x60,       /* G1 结果：bit15:0 位置或扭矩值，bit23:16 舵机 ERROR */
  G1_FAULT  = 0x64,       /* G1 故障码：3 超时 4 长度 5 停止位 6 应答 ID 7 校验 8 舵机错误 13 路径不允许 */

  G2_ID     = 0x68,       /* G2 单轴：目标 ID（calibrate-step 用） */
  G2_DELTA  = 0x6c,       /* G2 单轴：相对位移，-50..50 */

  PARAM0    = 0x90,       /* 六轴参数，每轴 +4，低 16 位原始速度、高 16 位原始时间 */

  FEEDBACK0 = 0xa8,       /* 六轴发后反馈，每轴 +4：bit15:0 位置，bit23:16 舵机 ERROR */
  STATUS    = 0xc0,       /* G2 状态：bit0 忙、bit1 完成、bit2 错误、bit4 本命令已发过 WRITE */
  FAULT     = 0xc4,       /* G2 故障：bit7:0 故障码，bit15:8 故障轴 */

  CMD         = 0xc8,     /* G2 命令字：0x47320003 六轴同步、0x47320004 单轴步进、0x47320005 停止 */
  DEADLINE_LO = 0xcc,     /* 命令截止时间（PL 自由计数器域） */
  DEADLINE_HI = 0xd0,

  CAL_START = 0xd4,       /* 单轴步进的实测起点 */
  CAL_MASK  = 0xd8,       /* 标定掩码，bit n 对应 ID n+1；六轴同步要求 0x3F */

  LOG_COUNT   = 0xdc,     /* bit7:0 样本数、bit16 起点有效、bit17 写应答有效 */
  LOG_INDEX   = 0xe0,     /* 选读第几条样本 */
  LOG_DATA    = 0xe4,     /* bit15:0 位置、bit23:16 舵机 ERROR、bit24 位置有效、bit31:28 读故障 */
  LOG_ELAPSED = 0xe8,     /* 样本时刻（100 kHz 计数） */

  LIMIT_ID        = 0xec, /* 限位选轴器（读限位与写容差共用此寄存器） */
  LIMIT_MIN       = 0xf0,
  LIMIT_MAX       = 0xf4,
  LIMIT_REFERENCE = 0xf8,
  LIMIT_SPEED_MAX = 0xfc,

  TOLERANCE = 0x100,      /* 逐轴容差，1..100 */
  OBSERVE   = 0x104,      /* 观察期，单位 100 ms */
  IGNORE    = 0x11c,      /* 只写：{到位掩码[11:6], 错误掩码[5:0]} */
  START_POSITION = 0x108, /* 各轴本次命令的起点（bit n 有效位在 RESULT 里） */

  RESULT = 0x10c,         /* bit0..5 起点有效、bit8..13 反馈有效、bit16..21 观察到位移、bit24..29 到位 */
  DIAG   = 0x110,         /* bit3:0 引擎故障码、bit11:8 发生阶段（1 发前读 2 写/应答 3 发后反馈）、bit23:16 舵机原始 ERROR */

  /* G1_STATUS 位 */
  BUSY      = 1,
  DONE      = 2,
  ERROR     = 4,
  INHIBITED = 8,
  SENT      = 16,         /* G2：本命令已发出 WRITE */
};

static volatile sig_atomic_t interrupted;
static void on_signal(int sig) { (void)sig; interrupted = 1; }

static uint64_t milliseconds(void) {
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC, &t)) return 0;
  return (uint64_t)t.tv_sec * 1000U + (uint64_t)t.tv_nsec / 1000000U;
}

static void pause_ms(unsigned n) {
  struct timespec t = {n / 1000U, (long)(n % 1000U) * 1000000L};
  while (nanosleep(&t, &t) && errno == EINTR && !interrupted) {}
}

/* ── 参数解析 ───────────────────────────────────────────────────────── */

static int parse_u16(const char *s, unsigned *out) {
  char *end;
  unsigned long v;
  if (!s || !*s || *s == '-' || *s == '+') return -1;
  errno = 0;
  v = strtoul(s, &end, 10);
  if (errno || *end || v > UINT16_MAX) return -1;
  *out = (unsigned)v;
  return 0;
}

static int parse_step(const char *s, int *out) {
  char *end;
  long v;
  if (!s || !*s) return -1;
  errno = 0;
  v = strtol(s, &end, 10);
  if (errno || *end || v == 0 || v < -50 || v > 50) return -1;
  *out = (int)v;
  return 0;
}

static int parse_axis(const char *value, unsigned *id, unsigned *target,
                      unsigned *speed, unsigned *time_raw) {
  char text[96], *parts[4], *next;
  if (strlen(value) >= sizeof(text)) return -1;
  strcpy(text, value);
  next = text;
  for (int i = 0; i < 4; i++) {
    parts[i] = next;
    if (i < 3) {
      next = strchr(next, ':');
      if (!next) return -1;
      *next++ = 0;
    } else if (strchr(next, ':')) {
      return -1;
    }
  }
  return parse_u16(parts[0], id) || parse_u16(parts[1], target) ||
         parse_u16(parts[2], speed) || parse_u16(parts[3], time_raw) ? -1 : 0;
}

static int parse_tolerance_axis(const char *s, unsigned *id, unsigned *tol) {
  char copy[32], *colon;
  if (strlen(s) >= sizeof(copy)) return -1;
  strcpy(copy, s);
  colon = strchr(copy, ':');
  if (!colon || strchr(colon + 1, ':')) return -1;
  *colon++ = 0;
  return parse_u16(copy, id) || parse_u16(colon, tol) ||
         *id < 1 || *id > 6 || *tol < 1 || *tol > 100 ? -1 : 0;
}

/* ── PL 自由计数器与命令截止时间 ────────────────────────────────────── */

static uint64_t ticks(volatile uint32_t *r) {
  uint32_t hi, lo, hi2;
  do {                       /* 高字前后各读一次，避免跨进位撕裂 */
    hi = r[TICKS_HI / 4];
    lo = r[TICKS_LO / 4];
    hi2 = r[TICKS_HI / 4];
  } while (hi != hi2);
  return ((uint64_t)hi << 32) | lo;
}

/* 给本次命令装 2e8 个计数的截止时间；PL 在提交时复核，过期即拒发。 */
static void set_deadline(volatile uint32_t *r) {
  uint64_t end = ticks(r) + 200000000ULL;
  r[DEADLINE_LO / 4] = (uint32_t)end;
  r[DEADLINE_HI / 4] = (uint32_t)(end >> 32);
}

/* ── 单轴读结果：走 G1 白名单事务 ───────────────────────────────────── */

/*
 * 通过 G1 路径做一次只读事务并取回 16 位值。
 * 只应传入 G1 白名单允许的操作码（1/2/9/11）；PL 会拒绝其它操作码并报 fault 13。
 * 成功条件：DONE 且无 ERROR 且状态包里的舵机 ERROR 字节为 0，三者缺一即失败。
 */
static int read_register(volatile uint32_t *r, unsigned id, unsigned op,
                         unsigned *value_out) {
  uint64_t end;
  if (r[G1_STATUS / 4] & BUSY) {
    fprintf(stderr, "ERR READ id=%u op=%u bus_busy\n", id, op);
    return -1;
  }
  r[G1_CMD / 4] = 2; __sync_synchronize();          /* 先清上一次的事务 */
  r[G1_ID / 4] = id;
  r[G1_OP / 4] = op; __sync_synchronize();
  r[G1_CMD / 4] = 1;                                /* 再启动 */
  end = milliseconds() + 300;
  do {
    uint32_t st = r[G1_STATUS / 4];
    if (st & DONE) {
      uint32_t value = r[G1_RESULT / 4];
      if (st & ERROR || ((value >> 16) & 255U)) {
        fprintf(stderr, "ERR READ id=%u op=%u fault=%" PRIu32 " servo_error=%u\n",
                id, op, r[G1_FAULT / 4], (value >> 16) & 255U);
        return -1;
      }
      *value_out = value & 65535U;
      return 0;
    }
    if (st & INHIBITED || interrupted) break;
    pause_ms(1);
  } while (milliseconds() < end);
  r[G1_CMD / 4] = 2;                                /* 超时：清掉未完成事务 */
  fprintf(stderr, "ERR READ id=%u op=%u timeout_or_inhibit\n", id, op);
  return -1;
}

/*
 * 只读的"发后单轴诊断"。故障码 8 表示收到校验有效但 ERROR 非零的状态包，
 * 只有这种情况才允许相信随包返回的位置；其它 READ 故障一律标 UNAVAILABLE。
 * 返回 0 正常、1 舵机自报错误、-1 其它读故障。
 */
static int diagnose_position(volatile uint32_t *r, unsigned id) {
  uint64_t end;
  if (r[G1_STATUS / 4] & BUSY) {
    printf("diagnose id=%u position_raw=UNAVAILABLE servo_error=UNAVAILABLE"
           " read_fault=BUSY status=READ_FAULT position_valid=0 epoch_ms=%" PRIu64 "\n",
           id, epoch_ms());
    return -1;
  }
  r[G1_CMD / 4] = 2; __sync_synchronize();
  r[G1_ID / 4] = id;
  r[G1_OP / 4] = 2; __sync_synchronize();
  r[G1_CMD / 4] = 1;
  end = milliseconds() + 300;
  do {
    uint32_t st = r[G1_STATUS / 4];
    if (st & DONE) {
      uint32_t fault = r[G1_FAULT / 4], value = r[G1_RESULT / 4];
      unsigned error = (value >> 16) & 255U;
      if (fault == 0 && !(st & ERROR) && error == 0) {
        printf("diagnose id=%u position_raw=%u servo_error=0x00"
               " read_fault=0 status=OK servo_error_bits=none position_valid=1"
               " epoch_ms=%" PRIu64 "\n",
               id, value & 65535U, epoch_ms());
        return 0;
      }
      if (fault == 8 && (st & ERROR) && error != 0) {
        printf("diagnose id=%u position_raw=%u servo_error=0x%02x"
               " read_fault=8 status=SERVO_ERROR servo_error_bits=",
               id, value & 65535U, error);
        print_servo_error_bits(stdout, error);
        printf(" position_valid=1 epoch_ms=%" PRIu64 "\n", epoch_ms());
        return 1;
      }
      printf("diagnose id=%u position_raw=UNAVAILABLE servo_error=UNAVAILABLE"
             " read_fault=%" PRIu32 " status=READ_FAULT position_valid=0"
             " read_fault_reason=%s epoch_ms=%" PRIu64 "\n",
             id, fault, engine_fault_name(fault), epoch_ms());
      return -1;
    }
    if (st & INHIBITED || interrupted) break;
    pause_ms(1);
  } while (milliseconds() < end);
  r[G1_CMD / 4] = 2;
  printf("diagnose id=%u position_raw=UNAVAILABLE servo_error=UNAVAILABLE"
         " read_fault=TIMEOUT_OR_INHIBIT status=READ_FAULT position_valid=0"
         " epoch_ms=%" PRIu64 "\n",
         id, epoch_ms());
  return -1;
}

/* ── 输出辅助 ───────────────────────────────────────────────────────── */

static const char *fault_reason(unsigned code) {
  switch (code) {
    case 1:  return "physical_tx_disabled";
    case 2:  return "bus_busy";
    case 3:  return "invalid_descriptor_or_step";
    case 4:  return "command_deadline_expired";
    case 5:  return "read_or_protocol_failure";
    case 8:  return "write_or_ack_failure";
    case 9:  return "three_consecutive_in_band_not_seen_before_observation_deadline";
    case 11: return "six_axis_uncalibrated";
    case 12: return "measured_limit_rejected";
    case 14: return "calibration_log_overflow";
    case 15: return "speed_raw_outside_1_1500";
    case 16: return "in_band_without_observed_position_change";
    case 17: return "tolerance_outside_1_100";
    case 18: return "observation_outside_1000_10000ms";
    default: return "unknown";
  }
}

static const char *phase_name(unsigned phase) {
  switch (phase) {
    case 1:  return "pre_write_read";
    case 2:  return "write_or_ack";
    case 3:  return "post_write_feedback";
    default: return "pre_commit";
  }
}

/*
 * 单轴步进：把 PL 的 128 深反馈日志逐条打印出来。
 * LOG_DATA 的 bit24 是"位置有效"，只有有效样本才更新 final；
 * 起点有效（LOG_COUNT bit16）时才打印目标与目标误差，避免把推算值当读数。
 */
static void print_calibration_log(volatile uint32_t *r, unsigned id, int delta,
                                  uint32_t st) {
  uint32_t meta = r[LOG_COUNT / 4], count = meta & 255U;
  unsigned start = r[CAL_START / 4], target = 0, final = 0, have_final = 0;

  if (meta & (1U << 16)) {
    target = (unsigned)((int)start + delta);
    printf("calibrate-start id=%u position_raw=%u target=%u requested_delta=%d"
           " write_sent=%u write_ack=%u\n",
           id, start, target, delta, (st & SENT) != 0, (meta >> 17) & 1U);
  } else {
    printf("calibrate-start id=%u position_raw=UNAVAILABLE target=UNAVAILABLE"
           " write_sent=%u write_ack=%u\n",
           id, (st & SENT) != 0, (meta >> 17) & 1U);
  }

  for (unsigned n = 0; n < count; n++) {
    uint32_t data, elapsed;
    unsigned valid, position;
    r[LOG_INDEX / 4] = n; __sync_synchronize();      /* 选读第 n 条样本 */
    data = r[LOG_DATA / 4];
    elapsed = r[LOG_ELAPSED / 4];
    valid = (data >> 28) & 1U;
    position = data & 65535U;
    if (valid) { final = position; have_final = 1; }
    printf("sample=%u id=%u elapsed_ms=%" PRIu32 " position_raw=",
           n + 1, id, elapsed / 100000U);
    if (valid) printf("%u", position); else printf("UNAVAILABLE");
    printf(" servo_error=%u read_fault=%u", (data >> 16) & 255U, (data >> 24) & 15U);
    if (valid && (meta & (1U << 16)))
      printf(" target_error=%u", position > target ? position - target : target - position);
    putchar('\n');
  }

  if (have_final && (meta & (1U << 16)))
    printf("calibrate-final id=%u position_raw=%u target=%u final_error=%u"
           " actual_delta=%d samples=%u\n",
           id, final, target,
           final > target ? final - target : target - final,
           (int)final - (int)start, count);
  else
    printf("calibrate-final id=%u position_raw=UNAVAILABLE final_error=UNAVAILABLE"
           " samples=%u\n", id, count);
  fflush(stdout);
}

/*
 * 通用结果打印：把 RESULT 的四个 6 位掩码翻译出来。
 * 起点不存在时一律打印 UNAVAILABLE，绝不用目标或上次读数回填。
 */
static void print_motion_result(volatile uint32_t *r, const char *verb,
                                const unsigned goals[6], unsigned cal_id,
                                uint64_t snapshot_epoch_ms) {
  uint32_t flags = r[RESULT / 4];
  for (unsigned id = 1; id <= 6; id++) {
    unsigned bit, start = 0, last = 0, target;
    if (!strcmp(verb, "calibrate-step") && id != cal_id) continue;
    bit = 1U << (id - 1);
    target = goals[id - 1];
    r[LIMIT_ID / 4] = id; __sync_synchronize();      /* 起点按轴选读 */
    if (flags & bit) start = r[START_POSITION / 4] & 65535U;
    if (!strcmp(verb, "stop") && (flags & bit)) target = start;  /* 停止=保持起点 */
    if (flags & (bit << 8)) last = r[(FEEDBACK0 + 4 * (id - 1)) / 4] & 65535U;

    printf("result id=%u start=", id);
    if (flags & bit) printf("%u", start); else printf("UNAVAILABLE");
    printf(" target=");
    if (!(flags & bit) && (!strcmp(verb, "stop") || !strcmp(verb, "calibrate-step")))
      printf("UNAVAILABLE");
    else printf("%u", target);
    printf(" last=");
    if (flags & (bit << 8)) printf("%u", last); else printf("UNAVAILABLE");
    printf(" actual_delta=");
    if ((flags & bit) && (flags & (bit << 8))) printf("%d", (int)last - (int)start);
    else printf("UNAVAILABLE");
    printf(" target_error=");
    if (flags & (bit << 8)) printf("%u", last > target ? last - target : target - last);
    else printf("UNAVAILABLE");
    printf(" position_change_observed=");
    if (flags & bit) printf("%u", (flags & (bit << 16)) != 0); else printf("UNAVAILABLE");
    printf(" in_band=");
    if (flags & (bit << 8)) printf("%u", (flags & (bit << 24)) != 0); else printf("UNAVAILABLE");
    printf(" start_valid=%u last_valid=%u snapshot_epoch_ms=%" PRIu64 "\n",
           (flags & bit) != 0, (flags & (bit << 8)) != 0, snapshot_epoch_ms);
  }
  fflush(stdout);
}

/*
 * 读 PL 编译进 bitstream 的实测限位。LIMIT_ID 兼作"选轴器"，读之前必须先写。
 * 任何一项非法（未标定、lo>hi、speed_max 为 0）都返回 -1，交由调用方拒绝命令。
 */
static int read_limit(volatile uint32_t *r, unsigned id, unsigned *lo,
                      unsigned *hi, unsigned *reference, unsigned *speed_max) {
  if (id < 1 || id > 6 || !(r[CAL_MASK / 4] & (1U << (id - 1)))) return -1;
  r[LIMIT_ID / 4] = id; __sync_synchronize();
  if (r[LIMIT_ID / 4] != id) return -1;              /* 回读确认选轴生效 */
  *lo = r[LIMIT_MIN / 4];
  *hi = r[LIMIT_MAX / 4];
  *reference = r[LIMIT_REFERENCE / 4];
  *speed_max = r[LIMIT_SPEED_MAX / 4];
  return *lo <= *hi && *hi <= UINT16_MAX &&
         *speed_max > 0 && *speed_max <= UINT16_MAX ? 0 : -1;
}

static void usage(const char *name) {
  fprintf(stderr,
    "usage: %s --uio /dev/uioN limits\n"
    "       %s --uio /dev/uioN diagnose\n"
    "       %s --uio /dev/uioN torque-status --id 1..6\n"
    "       %s --uio /dev/uioN calibrate-step --id 2..6 --delta -50..50"
    " [--tolerance 1..100] [--observe-ms 1000..10000] --execute\n"
    "       %s --uio /dev/uioN move-six --axis ID:target:speed-raw:time-raw"
    " (repeat six times) [--tolerance ID:1..100]..."
    " [--ignore-error ID] [--ignore-arrival ID]"
    " [--observe-ms 1000..10000] --execute\n"
    "       %s --uio /dev/uioN stop --execute\n"
    "limits / diagnose / torque-status 是只读命令，不接受 --execute。\n",
    name, name, name, name, name, name);
}

/* ── 主流程 ─────────────────────────────────────────────────────────── */

int main(int argc, char **argv) {
  const char *path = NULL, *verb = NULL;
  unsigned id = 0, seen_id = 0, seen_delta = 0, execute = 0;
  unsigned axis_mask = 0, tol_mask = 0;
  unsigned goal[6] = {0}, speed[6] = {0}, time_raw[6] = {0};
  unsigned err_mask = 0, arr_mask = 0;   /* --ignore-error / --ignore-arrival */
  unsigned tol[6] = {30, 30, 30, 30, 30, 30}, cal_tol = 5, observe_ms = 5000;
  unsigned seen_observe = 0, seen_cal_tol = 0;
  int delta = 0, fd = -1, rc = EXIT_FAILURE, requested_stop = 0;
  volatile uint32_t *r;
  void *map;
  uint64_t end, start;

  /* ── 第一段：参数解析。所有"缺参/多参/互斥"都在这里一次性拒绝，
   *    绝不在打开设备之后才发现参数不合法。 ───────────────────────── */
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--uio") && i + 1 < argc) {
      path = argv[++i];
    } else if (!strcmp(argv[i], "--id") && i + 1 < argc) {
      seen_id++, seen_id += (parse_u16(argv[++i], &id) != 0);
    } else if (!strcmp(argv[i], "--delta") && i + 1 < argc) {
      seen_delta++, seen_delta += (parse_step(argv[++i], &delta) != 0);
    } else if (!strcmp(argv[i], "--observe-ms") && i + 1 < argc) {
      seen_observe++, seen_observe += (parse_u16(argv[++i], &observe_ms) != 0);
    } else if (!strcmp(argv[i], "--tolerance") && i + 1 < argc) {
      const char *value = argv[++i];
      if (strchr(value, ':')) {                      /* 逐轴形式 ID:容差 */
        unsigned n, t;
        if (parse_tolerance_axis(value, &n, &t) || (tol_mask & (1U << (n - 1)))) {
          usage(argv[0]);
          return rc;
        }
        tol_mask |= 1U << (n - 1);
        tol[n - 1] = t;
      } else {                                       /* 单轴步进的全局容差 */
        seen_cal_tol++, seen_cal_tol += (parse_u16(value, &cal_tol) != 0);
      }
    } else if (!strcmp(argv[i], "--axis") && i + 1 < argc) {
      unsigned n, t, s, tm;
      if (parse_axis(argv[++i], &n, &t, &s, &tm) || n < 1 || n > 6 ||
          (axis_mask & (1U << (n - 1)))) {
        usage(argv[0]);
        return rc;
      }
      axis_mask |= 1U << (n - 1);
      goal[n - 1] = t;
      speed[n - 1] = s;
      time_raw[n - 1] = tm;
    } else if (!strcmp(argv[i], "--ignore-error") && i + 1 < argc) {
      unsigned n;
      if (parse_u16(argv[++i], &n) || n < 1 || n > 6 || (err_mask & (1U << (n - 1)))) {
        usage(argv[0]);
        return rc;
      }
      err_mask |= 1U << (n - 1);
    } else if (!strcmp(argv[i], "--ignore-arrival") && i + 1 < argc) {
      unsigned n;
      if (parse_u16(argv[++i], &n) || n < 1 || n > 6 || (arr_mask & (1U << (n - 1)))) {
        usage(argv[0]);
        return rc;
      }
      arr_mask |= 1U << (n - 1);
    } else if (!strcmp(argv[i], "--execute")) {
      execute++;
    } else if (!verb && (!strcmp(argv[i], "limits") ||
                         !strcmp(argv[i], "diagnose") ||
                         !strcmp(argv[i], "calibrate-step") ||
                         !strcmp(argv[i], "torque-status") ||
                         !strcmp(argv[i], "move-six") ||
                         !strcmp(argv[i], "stop"))) {
      verb = argv[i];
    } else {
      usage(argv[0]);
      return rc;
    }
  }

  /* 每个动词允许出现哪些参数，在这里逐条钉死。 */
  if (!path || !verb || execute > 1 || seen_observe > 1 || seen_cal_tol > 1 ||
      observe_ms < 1000 || observe_ms > 10000 || observe_ms % 100 ||
      cal_tol < 1 || cal_tol > 100 ||
      ((err_mask || arr_mask) && strcmp(verb, "move-six")) ||
      (!strcmp(verb, "limits") && (execute || seen_id || seen_delta || axis_mask ||
                                   tol_mask || seen_cal_tol || seen_observe)) ||
      (!strcmp(verb, "diagnose") && (execute || seen_id || seen_delta || axis_mask ||
                                     tol_mask || seen_cal_tol || seen_observe)) ||
      (!strcmp(verb, "torque-status") && (execute || seen_id != 1 || id < 1 || id > 6 ||
                                          seen_delta || axis_mask || tol_mask ||
                                          seen_cal_tol || seen_observe)) ||
      (!strcmp(verb, "calibrate-step") && (execute != 1 || seen_id != 1 ||
                                           seen_delta != 1 || id < 2 || id > 6 ||
                                           axis_mask || tol_mask)) ||
      (!strcmp(verb, "move-six") && (execute != 1 || seen_id || seen_delta ||
                                     axis_mask != 63U || seen_cal_tol)) ||
      (!strcmp(verb, "stop") && (execute != 1 || seen_id || seen_delta || axis_mask ||
                                 tol_mask || seen_cal_tol || seen_observe))) {
    usage(argv[0]);
    return rc;
  }

  /* ── 第二段：打开 UIO、独占总线、映射寄存器、核对 ABI。
   *    flock 是总线互斥：两个 CLI 同时跑会把 PL 的状态机搅乱。 ─────── */
  fd = open(path, O_RDWR | O_SYNC);
  if (fd < 0) { perror("ERR open_uio"); return rc; }
  if (flock(fd, LOCK_EX | LOCK_NB)) { perror("ERR bus_locked"); close(fd); return rc; }
  map = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (map == MAP_FAILED) { perror("ERR mmap_uio"); close(fd); return rc; }
  r = (volatile uint32_t *)map;

  if (r[ID / 4] != ABI && r[ID / 4] != ABI_0D) {
    fprintf(stderr, "ERR incompatible_pl_id=0x%08" PRIx32 " expected=0x%08x\n",
            r[ID / 4], ABI);
    goto out;
  }
  if (r[ID / 4] != ABI)
    fprintf(stderr, "WARN pl_abi=0x%08" PRIx32 " expected=0x%08x: 寄存器映射兼容，"
                   "六轴路径无 G2_DIAG 锁存；且 0D PL 在广播前会先 READ 六轴起点，"
                   "只要任一轴的 READ 的舵机 ERROR 非零就以 fault=5/write_sent=0 "
                   "拦下整条命令（0E 已删除该阶段）\n", r[ID / 4], ABI);

  printf("RTCS_PL_G2_SIX abi=0x%08" PRIx32 " physical_tx=%s calibrated_mask=0x%02" PRIx32
         "\n", r[ID / 4], r[G1_STATUS / 4] & INHIBITED ? "DISABLED" : "ENABLED",
         r[CAL_MASK / 4] & 63U);

  /* ── limits（只读）：读 PL 编译期的实测限位表 ───────────────────── */
  if (!strcmp(verb, "limits")) {
    for (unsigned n = 1; n <= 6; n++) {
      unsigned lo, hi, reference, speed_max;
      if (read_limit(r, n, &lo, &hi, &reference, &speed_max)) {
        fprintf(stderr, "ERR missing_or_invalid_pl_limit id=%u\n", n);
        goto out;
      }
      printf("limit id=%u min=%u max=%u reference_count=%u speed_raw_max=%u\n",
             n, lo, hi, reference, speed_max);
    }
    puts("RTCS_PL_G2_SIX_LIMITS_OK calibrated_mask=0x3f");
    rc = EXIT_SUCCESS;
    goto out;
  }

  /* 物理禁发时，除了只读的 limits，其余一律不执行。 */
  if (r[G1_STATUS / 4] & INHIBITED) {
    fputs("ERR physical_tx_disabled\n", stderr);
    goto out;
  }
  signal(SIGINT, on_signal);
  signal(SIGTERM, on_signal);

  /* ── diagnose（只读）：逐轴 READ_POSITION 并解释故障 ────────────── */
  if (!strcmp(verb, "diagnose")) {
    unsigned issues = 0;
    for (unsigned n = 1; n <= 6; n++) {
      if (diagnose_position(r, n) != 0) issues++;
      if (interrupted) break;
    }
    printf("RTCS_PL_G2_SIX_DIAG %s issues=%u read_only=1 write_sent=0\n",
           issues || interrupted ? "INCOMPLETE" : "OK", issues);
    if (!issues && !interrupted) rc = EXIT_SUCCESS;
    goto out;
  }

  /* ── torque-status（只读）：G1 白名单的 READ_TORQUE(0x28) ────────── */
  if (!strcmp(verb, "torque-status")) {
    unsigned torque;
    if (read_register(r, id, 11, &torque)) goto out;
    printf("RTCS_PL_G2_SIX_TORQUE id=%u register=0x28 value=%u\n", id, torque & 255U);
    rc = EXIT_SUCCESS;
    goto out;
  }

  /* ── 以下是会发帧的命令：先做 PS 侧发前校验，再提交命令字 ───────── */

  /* stop 允许在 G2 忙时提交（它是收敛动作），其余命令必须等总线空。 */
  if (r[STATUS / 4] & BUSY && strcmp(verb, "stop")) {
    fputs("ERR g2_busy\n", stderr);
    goto out;
  }

  /* move-six：六轴必须全部标定过，否则拒绝（PL 侧也会再查一次）。 */
  if (!strcmp(verb, "move-six") && (r[CAL_MASK / 4] & 63U) != 63U) {
    fputs("ERR six_axis_uncalibrated; measured limits must be compiled into PL\n", stderr);
    goto out;
  }

  /* move-six 发前逐轴校验目标与原始速度。
   * 注意：PL 的提交校验读的是同一组编译期常量，所以这层是 UX 与早失败，
   * 真正的门禁在 PL。 */
  if (!strcmp(verb, "move-six")) {
    for (unsigned n = 1; n <= 6; n++) {
      unsigned lo, hi, reference, speed_max;
      if (read_limit(r, n, &lo, &hi, &reference, &speed_max)) {
        fprintf(stderr, "ERR missing_or_invalid_pl_limit id=%u\n", n);
        goto out;
      }
      if (goal[n - 1] < lo || goal[n - 1] > hi || speed[n - 1] == 0 ||
          speed[n - 1] > speed_max) {
        fprintf(stderr, "ERR axis=%u target_or_speed_outside_pl_limit"
                        " target=%u speed_raw=%u range=%u..%u speed_max=%u\n",
                n, goal[n - 1], speed[n - 1], lo, hi, speed_max);
        goto out;
      }
    }
  }

  /* 单轴步进：PL 必须先知道起点才能算目标，所以这里保留功能性发前 READ；
   * 该轴的最大原始速度必须够 500，否则 PL 会拒发。 */
  if (!strcmp(verb, "calibrate-step")) {
    unsigned lo, hi, reference, speed_max;
    if (read_limit(r, id, &lo, &hi, &reference, &speed_max) || speed_max < 500) {
      fprintf(stderr, "ERR missing_or_invalid_pl_limit id=%u\n", id);
      goto out;
    }
    r[G2_ID / 4] = id;
    r[G2_DELTA / 4] = (uint32_t)delta;
    tol[id - 1] = cal_tol;
    printf("calibrate-step id=%u delta=%d speed_raw=500 time_raw=10"
           " tolerance=%u observe_ms=%u\n", id, delta, cal_tol, observe_ms);
  } else if (!strcmp(verb, "move-six")) {
    r[IGNORE / 4] = (arr_mask << 6) | err_mask;
    for (unsigned n = 0; n < 6; n++) {
      r[(TARGET0 + 4 * n) / 4] = goal[n];
      r[(PARAM0 + 4 * n) / 4] = (time_raw[n] << 16) | speed[n];
      printf("axis=%u target=%u speed_raw=%u time_raw=%u tolerance=%u"
             " torque=0x28:1\n", n + 1, goal[n], speed[n], time_raw[n], tol[n]);
    }
    printf("ignore error_mask=0x%02x arrival_mask=0x%02x\n", err_mask, arr_mask);
  } else {
    puts("stop_requested=READ_six_then_SYNC_hold; completion_not_yet_confirmed");
  }

  /* stop 不发运动目标，因此不写容差与观察期。 */
  if (strcmp(verb, "stop")) {
    for (unsigned n = 1; n <= 6; n++) {
      r[LIMIT_ID / 4] = n; __sync_synchronize();     /* 用同一选轴器逐轴写容差 */
      r[TOLERANCE / 4] = tol[n - 1];
    }
    r[OBSERVE / 4] = observe_ms / 100;
  }

  /* ── 提交命令字，然后轮询到 DONE / 超时 ─────────────────────────── */
  set_deadline(r);
  __sync_synchronize();
  start = milliseconds();
  r[CMD / 4] = !strcmp(verb, "calibrate-step") ? 0x47320004U :
               !strcmp(verb, "move-six")        ? 0x47320003U : 0x47320005U;
  pause_ms(1);                     /* 避免读到上一条命令残留的 DONE */
  end = start + 13000;

  for (;;) {
    uint32_t st = r[STATUS / 4];
    if (st & DONE) {
      uint32_t fault = r[FAULT / 4];
      uint64_t snapshot_epoch_ms;
      uint32_t flags, diag;
      uint32_t incident_g1_fault, incident_g1_result;
      unsigned incident_valid, expected;

      if (!strcmp(verb, "calibrate-step")) {
        print_calibration_log(r, id, delta, st);
        if (r[LOG_COUNT / 4] & (1U << 16))
          goal[id - 1] = (unsigned)((int)r[CAL_START / 4] + delta);
      }
      snapshot_epoch_ms = epoch_ms();
      print_motion_result(r, verb, goal, id, snapshot_epoch_ms);

      flags = r[RESULT / 4];
      diag = r[DIAG / 4];
      incident_g1_fault = r[G1_FAULT / 4];
      incident_g1_result = r[G1_RESULT / 4];
      /* 只有当 PL 锁存的阶段与 G1 快照指向同一次事件时，才认这条故障位置。 */
      incident_valid = (fault & 255U) == 5 && (diag & 15U) == 8U &&
                       incident_g1_fault == 8U &&
                       ((incident_g1_result >> 16) & 255U) == ((diag >> 16) & 255U) &&
                       (((diag >> 8) & 255U) == 1U || ((diag >> 8) & 255U) == 3U);
      expected = !strcmp(verb, "calibrate-step") ? (1U << (id - 1)) : 63U;

      printf("command_result write_sent=%u unicast_ack=", (st & SENT) != 0);
      if (!strcmp(verb, "calibrate-step"))
        printf("%u", (r[LOG_COUNT / 4] >> 17) & 1U);
      else
        printf("NOT_APPLICABLE_BROADCAST");        /* 广播没有协议 ACK */
      printf(" fault=%u fault_id=%u start_valid_mask=0x%02x feedback_valid_mask=0x%02x",
             fault & 255U, (fault >> 8) & 255U, flags & 63U, (flags >> 8) & 63U);
      if (!strcmp(verb, "move-six")) printf(" position_change_mask=UNAVAILABLE");
      else printf(" position_change_mask=0x%02x", (flags >> 16) & 63U);
      printf(" phase=%s engine_fault=%u", phase_name((diag >> 8) & 255U), diag & 15U);
      printf(" servo_error_raw=");
      if ((diag & 15U) == 8U) printf("0x%02x", (diag >> 16) & 255U);
      else printf("UNAVAILABLE");
      printf(" servo_error_bits=");
      if ((diag & 15U) == 8U) print_servo_error_bits(stdout, (diag >> 16) & 255U);
      else printf("UNAVAILABLE");
      printf(" incident_position=");
      if (incident_valid) printf("%u", incident_g1_result & 65535U);
      else printf("UNAVAILABLE");
      printf(" incident_position_valid=%u stage=%s snapshot_epoch_ms=%" PRIu64
             " elapsed_ms=%" PRIu64,
             incident_valid,
             (fault & 255U) == 9 || (fault & 255U) == 16 ? "stability_check"
                                                         : phase_name((diag >> 8) & 255U),
             snapshot_epoch_ms, milliseconds() - start);
      printf(" engine_class=%s engine_reason=%s",
             engine_fault_class(diag & 15U), engine_fault_name(diag & 15U));
      putchar('\n');

      if (st & ERROR || (fault & 255U) != 0 || !(st & SENT)) {
        /* 失败分支：PL 的结果就是失败记录。 */
        fprintf(stderr, "ERR g2_six_fault=%u fault_id=%u write_sent=%u"
                        " reason=%s phase=%s engine_fault=%u engine_class=%s"
                        " engine_reason=%s",
                fault & 255U, (fault >> 8) & 255U, (st & SENT) != 0,
                fault_reason(fault & 255U), phase_name((diag >> 8) & 255U), diag & 15U,
                engine_fault_class(diag & 15U), engine_fault_name(diag & 15U));
        if ((diag & 15U) == 8U)
          fprintf(stderr, " servo_error_raw=0x%02x", (diag >> 16) & 255U);
        fputc('\n', stderr);

        /* 广播发后 READ 失败时，只对"还没有反馈样本"的轴补一次只读 READ。
         * 每次 G1 READ 有 300 ms 上界，且绝不再发运动帧；补采结果不改原判定。 */
        if (!interrupted && !strcmp(verb, "move-six") && (st & SENT) &&
            (fault & 255U) == 5 && ((diag >> 8) & 255U) == 3 &&
            ((fault >> 8) & 255U) >= 1 && ((fault >> 8) & 255U) <= 6 &&
            !(r[G1_STATUS / 4] & INHIBITED)) {
          unsigned remaining = (~(flags >> 8)) & 63U;
          remaining &= ~(1U << (((fault >> 8) & 255U) - 1U));
          printf("post_fault_read_only original_fault=%u fault_id=%u"
                 " remaining_mask=0x%02x write_sent=0\n",
                 fault & 255U, (fault >> 8) & 255U, remaining);
          for (unsigned n = 1; n <= 6; n++) {
            if (!(remaining & (1U << (n - 1)))) continue;
            printf("post_fault_axis=%u ", n);
            (void)diagnose_position(r, n);
            if (interrupted) break;
          }
        }
      } else {
        /* 成功分支：必须四个掩码都对得上，否则不认这次结果。 */
        if (((flags >> 8) & expected) != expected ||
            ((flags >> 24) & expected) != expected ||
            (strcmp(verb, "move-six") && (flags & expected) != expected)) {
          fputs("ERR incomplete_result_snapshot\n", stderr);
          break;
        }
        for (unsigned n = 0; n < 6; n++) {
          uint32_t sample;
          if (!strcmp(verb, "calibrate-step") && n + 1 != id) continue;
          sample = r[(FEEDBACK0 + 4 * n) / 4];
          printf("feedback id=%u position_raw=%u servo_error=%u\n",
                 n + 1, sample & 65535U, (sample >> 16) & 255U);
        }
        if (requested_stop) {
          printf("RTCS_PL_G2_SIX_STOPPED after_interrupt elapsed_ms=%" PRIu64 "\n",
                 milliseconds() - start);
        } else {
          printf("RTCS_PL_G2_SIX_OK command=%s elapsed_ms=%" PRIu64 "\n",
                 verb, milliseconds() - start);
          rc = EXIT_SUCCESS;
        }
      }
      break;
    }

    /* 收到中断不直接退出：重装截止时间后提交一次软件急停请求。 */
    if (interrupted && !requested_stop) {
      requested_stop = 1;
      set_deadline(r);
      __sync_synchronize();
      r[CMD / 4] = 0x47320005U;
      fputs("ERR interrupted; software_stop_requested\n", stderr);
      end = milliseconds() + 13000;
    }
    if (milliseconds() > end) {
      fputs("ERR host_wait_timeout; WRITE may already have been sent\n", stderr);
      break;
    }
    pause_ms(5);
  }

  if (requested_stop) rc = EXIT_FAILURE;
out:
  munmap(map, MAP_SIZE);
  close(fd);
  return rc;
}
