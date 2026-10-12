/* ID 1..6 G2 motion. Each explicit command sends at most one motion frame.
 *
 * ABI 14 retains the 0x28..0x2F atomic motion frame, so the torque
 * switch (0x28, SRAM, power-on default 0 = 卸力) and the goal position land in
 * the same packet. A frame that only wrote 0x2A produced a valid ACK with
 * servo_error=0 and no motion. `release` is the only other bus write and only
 * clears the torque switch; it never writes a position.
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

/* 寄存器偏移、ABI 版本与状态位定义。 */
enum {
  MAP_BYTES = 0x10000,          /* UIO 映射大小 */
  ABI = 0x5254000e,             /* 期望的 PL ABI ID */
  ABI_0D = 0x5254000d,          /* 寄存器映射兼容的上一版 PL，无 G2_DIAG 锁存 */
  ID = 0x00,                    /* PL ID 寄存器偏移 */
  TICKS_LO = 0x14,              /* 64 位 tick 低 32 位 */
  TICKS_HI = 0x18,              /* 64 位 tick 高 32 位 */
  G1_ID = 0x50,                 /* G1 命令：ID */
  G1_OP = 0x54,                 /* G1 命令：操作码 */
  G1_CMD = 0x58,                /* G1 命令：命令触发 */
  G1_STATUS = 0x5c,             /* G1 命令：状态 */
  G1_RESULT = 0x60,             /* G1 命令：结果 */
  G1_FAULT = 0x64,              /* G1 命令：故障码 */
  G2_ID = 0x68,                 /* G2 运动：ID */
  G2_TOLERANCE_OBSERVE = 0x6c,  /* G2 运动：容差与观察时间 */
  G2_TARGET = 0x70,             /* G2 运动：目标位置 */
  G2_SPEED_TIME = 0x74,         /* G2 运动：速度与时间 */
  G2_DEADLINE_LO = 0x78,        /* G2 命令截止 tick 低 32 位 */
  G2_DEADLINE_HI = 0x7c,        /* G2 命令截止 tick 高 32 位 */
  G2_CMD = 0x80,                /* G2 命令触发 */
  G2_STATUS = 0x84,             /* G2 状态 */
  G2_FAULT = 0x88,              /* G2 故障码 */
  G2_FEEDBACK = 0x8c,           /* G2 反馈位置/错误 */
  G2_DIAG = 0x118,              /* G2 单轴故障锁存，只读；旧 PL 读回 0 */
  CAL_MASK = 0xd8,              /* 校准掩码 */
  LIMIT_ID = 0xec,              /* 限位：查询 ID */
  LIMIT_MIN = 0xf0,             /* 限位：最小位置 */
  LIMIT_MAX = 0xf4,             /* 限位：最大位置 */
  LIMIT_REFERENCE = 0xf8,       /* 限位：参考位置 */
  LIMIT_SPEED_MAX = 0xfc,       /* 限位：最大速度 */
  BUSY = 1,                     /* 状态：忙 */
  DONE = 2,                     /* 状态：完成 */
  ERROR = 4,                    /* 状态：错误 */
  INHIBITED = 8,                /* 状态：禁止 */
  WRITE_SENT = 16,              /* 状态：已发送写帧 */
  LATE = 32,                    /* 状态：晚于 2 秒 */
  FEEDBACK_VALID = 128,         /* 状态：反馈位置有效 */
  WRITE_ACK = 65536,            /* 状态：写 ACK */
  OP_TORQUE_OFF = 9             /* G1 操作码：卸力 */
};

static volatile sig_atomic_t interrupted; /* 收到 SIGINT/SIGTERM 时置位 */

static void on_signal(int sig)
{
  (void)sig;
  interrupted = 1;
}

static uint64_t now_ms(void)
{
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC, &t)) return 0;
  return (uint64_t)t.tv_sec * 1000 + (uint64_t)t.tv_nsec / 1000000;
}

static void pause_ms(unsigned ms)
{
  struct timespec t = { ms / 1000U, (long)(ms % 1000U) * 1000000L };
  while (nanosleep(&t, &t) && errno == EINTR && !interrupted) {}
}

/* 根据故障和状态推断运动阶段。 */
static const char *motion_phase(unsigned fault, unsigned st)
{
  if (fault == 9) return "stability_check";
  if (!(st & WRITE_SENT)) return "pre_commit";
  if (!(st & WRITE_ACK)) return "write_ack";
  return "post_write_read";
}

/* G2_DIAG[15:8] 的锁存阶段（比按状态位反推更准确）。 */
static const char *diag_phase_name(unsigned phase)
{
  switch (phase) {
    case 1: return "pre_commit";
    case 2: return "write_or_ack";
    case 3: return "post_write_feedback";
    default: return "unknown";
  }
}

/* 解析非负十进制无符号整数。 */
static int parse_uint(const char *s, unsigned *out)
{
  char *end = NULL;
  unsigned long v;
  if (!s || !*s || *s == '-' || *s == '+') return -1;
  errno = 0;
  v = strtoul(s, &end, 10);
  if (errno || !end || *end || v > UINT32_MAX) return -1;
  *out = (unsigned)v;
  return 0;
}

/* 读取 PL 提供的 64 位单调 tick，避免高低位撕裂。 */
static uint64_t ticks(volatile uint32_t *r)
{
  uint32_t hi, lo, hi2;
  do {
    hi = r[TICKS_HI / 4];
    lo = r[TICKS_LO / 4];
    hi2 = r[TICKS_HI / 4];
  } while (hi != hi2);
  return ((uint64_t)hi << 32) | lo;
}

/* Runs one G1-path command and returns its PL fault code, or -1 on transport
 * failure. Only OP_READ and OP_TORQUE_OFF pass the PL whitelist; any opcode
 * that can write a position is refused by the PL with fault 13. */
static int g1_command(volatile uint32_t *r, unsigned id, unsigned op,
                      unsigned *result)
{
  uint64_t deadline;
  uint32_t st;

  if (r[G1_STATUS / 4] & (BUSY | INHIBITED)) return -1;

  r[G1_CMD / 4] = 2;
  __sync_synchronize();
  r[G1_ID / 4] = id;
  r[G1_OP / 4] = op;
  __sync_synchronize();
  r[G1_CMD / 4] = 1;

  deadline = now_ms() + 300;
  do {
    st = r[G1_STATUS / 4];
    if (st & INHIBITED || interrupted) {
      r[G1_CMD / 4] = 2;
      return -1;
    }
    if (st & DONE) {
      if (st & ERROR) return (int)r[G1_FAULT / 4];
      *result = r[G1_RESULT / 4];
      return 0;
    }
    pause_ms(1);
  } while (now_ms() < deadline);

  r[G1_CMD / 4] = 2;
  fputs("ERR g1_host_wait_timeout\n", stderr);
  return -1;
}

static void usage(const char *p)
{
  fprintf(stderr,
          "usage: %s --uio /dev/uioN probe\n"
          "       %s --uio /dev/uioN release --id 1..6 --execute\n"
          "       %s --uio /dev/uioN move --id 1..6 --target N "
          "--speed-raw N --time-raw N [--tolerance 1..100]"
          " [--observe-ms 1000..10000] --execute\n",
          p, p, p);
}

int main(int argc, char **argv)
{
  const char *path = NULL;
  int probe = 0, move = 0, release = 0, execute = 0, fd;
  unsigned id = 0, target = 0, speed_raw = 0, time_raw = 0, position = 0;
  unsigned tolerance = 30, observe_ms = 5000;
  int seen_id = 0, seen_target = 0, seen_speed = 0, seen_time = 0,
      seen_tol = 0, seen_observe = 0;
  volatile uint32_t *r;
  void *mapping;
  uint32_t st = 0, last_samples = 0;
  uint64_t host_deadline, deadline_ticks, start_ms;
  int result = EXIT_FAILURE;

  /* 参数解析。 */
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--uio") && i + 1 < argc)
      path = argv[++i];
    else if (!strcmp(argv[i], "--id") && i + 1 < argc)
      seen_id++, seen_id += parse_uint(argv[++i], &id) != 0;
    else if (!strcmp(argv[i], "--target") && i + 1 < argc)
      seen_target++, seen_target += parse_uint(argv[++i], &target) != 0;
    else if (!strcmp(argv[i], "--speed-raw") && i + 1 < argc)
      seen_speed++, seen_speed += parse_uint(argv[++i], &speed_raw) != 0;
    else if (!strcmp(argv[i], "--time-raw") && i + 1 < argc)
      seen_time++, seen_time += parse_uint(argv[++i], &time_raw) != 0;
    else if (!strcmp(argv[i], "--tolerance") && i + 1 < argc)
      seen_tol++, seen_tol += parse_uint(argv[++i], &tolerance) != 0;
    else if (!strcmp(argv[i], "--observe-ms") && i + 1 < argc)
      seen_observe++, seen_observe += parse_uint(argv[++i], &observe_ms) != 0;
    else if (!strcmp(argv[i], "--execute"))
      execute++;
    else if (!strcmp(argv[i], "probe"))
      probe++;
    else if (!strcmp(argv[i], "move") || !strcmp(argv[i], "move-one"))
      move++;
    else if (!strcmp(argv[i], "release"))
      release++;
    else {
      usage(argv[0]);
      return EXIT_FAILURE;
    }
  }

  /* 参数组合校验。 */
  if (!path || (probe + move + release) != 1 || execute > 1 ||
      seen_tol > 1 || seen_observe > 1 ||
      tolerance < 1 || tolerance > 100 ||
      observe_ms < 1000 || observe_ms > 10000 || observe_ms % 100 ||
      (probe && (seen_id || execute ||
                 seen_target || seen_speed || seen_time || seen_tol ||
                 seen_observe)) ||
      (move + release > 0 && (seen_id != 1 || !execute)) ||
      (release && (seen_target || seen_speed || seen_time || seen_tol ||
                   seen_observe)) ||
      (move && (seen_target != 1 || seen_speed != 1 || seen_time != 1))) {
    usage(argv[0]);
    return EXIT_FAILURE;
  }

  if (move && (id < 1 || id > 6 || target > UINT16_MAX ||
               speed_raw > UINT16_MAX || time_raw > UINT16_MAX)) {
    fputs("ERR ID must be 1..6 and target/speed-raw/time-raw must fit 16 bits\n",
          stderr);
    return EXIT_FAILURE;
  }

  /* 卸力对所有轴开放：这是把某一轴卸载、以便不带载做机械检查的唯一手段，
   * 只写 0x28<-0、不写位置，方向上是让扭矩变小。G1 白名单本来就允许
   * TORQUE_OFF 用于任意 ID，旧版只放行 ID 1 是单轴调试期的遗留。 */
  if (release && (id < 1 || id > 6)) {
    fputs("ERR ID must be 1..6 for torque release\n", stderr);
    return EXIT_FAILURE;
  }

  /* 打开 UIO、加锁、映射 PL 寄存器。 */
  fd = open(path, O_RDWR | O_SYNC);
  if (fd < 0) {
    perror("ERR open_uio (use sudo)");
    return EXIT_FAILURE;
  }
  if (flock(fd, LOCK_EX | LOCK_NB)) {
    perror("ERR bus_locked");
    close(fd);
    return EXIT_FAILURE;
  }

  mapping = mmap(NULL, MAP_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (mapping == MAP_FAILED) {
    perror("ERR mmap_uio");
    close(fd);
    return EXIT_FAILURE;
  }
  r = (volatile uint32_t *)mapping;

  /* ABI 0D 与本版共享同一套寄存器映射，只少了 G2_DIAG 锁存与“绝对目标不预读
   * 起点”。允许在 0D 板端运行，是为了让操作者不必先重综合 bitstream 就能把
   * 故障归因看清楚；出现差异会显式告警，不静默混用。 */
  if (r[ID / 4] != ABI && r[ID / 4] != ABI_0D) {
    fprintf(stderr,
            "ERR incompatible_pl_id=0x%08" PRIx32 " expected=0x%08x\n",
            r[ID / 4], ABI);
    goto done;
  }
  if (r[ID / 4] != ABI)
    fprintf(stderr,
            "WARN pl_abi=0x%08" PRIx32 " expected=0x%08x: 寄存器映射兼容，但该 PL "
            "无 G2_DIAG 锁存；且 0D PL 在运动前会先做一次位置 READ，只要该 READ 的"
            "舵机 ERROR 非零就以 fault=5/write_sent=0 拦下整条命令（0E 已删除该阶段）。"
            "故障归因回退到 G1_FAULT/G1_RESULT\n",
            r[ID / 4], ABI);

  st = r[G1_STATUS / 4];
  printf("RTCS_PL_G2 board=AX7Z020B abi=0x%08" PRIx32 " physical_tx=%s\n",
         r[ID / 4], st & INHIBITED ? "DISABLED" : "ENABLED");

  if (probe) {
    result = EXIT_SUCCESS;
    goto done;
  }

  if (st & (BUSY | INHIBITED)) {
    fputs("ERR busy_or_inhibited\n", stderr);
    goto done;
  }

  signal(SIGINT, on_signal);
  signal(SIGTERM, on_signal);

  /* 卸力：只写 0x28<-0，不写目标位置，可重复执行。 */
  if (release) {
    int code = g1_command(r, id, OP_TORQUE_OFF, &position);
    if (code < 0) {
      fputs("ERR release_transport\n", stderr);
      goto done;
    }
    if (code != 0) {
      fprintf(stderr, "ERR release_fault=%d\n", code);
      goto done;
    }
    if ((position >> 16) & 0xffU) {
      fprintf(stderr, "ERR release_servo_error=0x%02" PRIx32 "\n",
              (position >> 16) & 0xffU);
      goto done;
    }
    printf("RTCS_PL_G2_RELEASE id=%u torque=OFF torque_register=0x28 value=0\n",
           id);
    result = EXIT_SUCCESS;
    goto done;
  }

  /* 校准与限位检查。 */
  if (!(r[CAL_MASK / 4] & (1U << (id - 1)))) {
    fprintf(stderr, "ERR axis_uncalibrated id=%u\n", id);
    goto done;
  }

  r[LIMIT_ID / 4] = id;
  __sync_synchronize();
  unsigned lo = r[LIMIT_MIN / 4], hi = r[LIMIT_MAX / 4];
  unsigned speed_max = r[LIMIT_SPEED_MAX / 4];

  if (r[LIMIT_ID / 4] != id || lo > hi || hi > UINT16_MAX ||
      speed_max == 0 || speed_max > UINT16_MAX) {
    fprintf(stderr, "ERR invalid_pl_limit id=%u\n", id);
    goto done;
  }

  if (target < lo || target > hi || speed_raw == 0 || speed_raw > speed_max) {
    fprintf(stderr,
            "ERR target_or_speed_outside_pl_limit id=%u target=%u"
            " speed_raw=%u range=%u..%u speed_max=%u\n",
            id, target, speed_raw, lo, hi, speed_max);
    goto done;
  }

  /* 提交 G2 运动命令。 */
  if (r[G2_STATUS / 4] & BUSY || r[G1_STATUS / 4] & INHIBITED || interrupted) {
    fputs("ERR changed_before_commit\n", stderr);
    goto done;
  }

  r[G2_ID / 4] = id;
  r[G2_TARGET / 4] = target;
  r[G2_SPEED_TIME / 4] = (time_raw << 16) | speed_raw;
  r[G2_TOLERANCE_OBSERVE / 4] = ((observe_ms / 100) << 16) | tolerance;

  deadline_ticks = ticks(r) + 200000000ULL; /* 2 s command deadline at 100 MHz */
  r[G2_DEADLINE_LO / 4] = (uint32_t)deadline_ticks;
  r[G2_DEADLINE_HI / 4] = (uint32_t)(deadline_ticks >> 32);

  __sync_synchronize();

  printf("commit id=%u target=%u speed_raw=%u time_raw=%u"
         " tolerance=%u observe_ms=%u torque_toggle=0x28:1"
         " command_deadline_ticks=%" PRIu64 "\n",
         id, target, speed_raw, time_raw, tolerance, observe_ms, deadline_ticks);
  fflush(stdout);

  start_ms = now_ms();
  r[G2_CMD / 4] = 0x47320001U;
  host_deadline = start_ms + 13000; /* <=2 s before WRITE + <=10 s PL observation + margin */

  /* 轮询 G2 状态与采样反馈。 */
  do {
    st = r[G2_STATUS / 4];
    if (((st >> 8) & 0xffU) != last_samples) {
      last_samples = (st >> 8) & 0xffU;
      uint32_t sample = r[G2_FEEDBACK / 4];
      printf("sample=%" PRIu32 " position_raw=%" PRIu32
             " servo_error_raw=0x%02" PRIx32
             " elapsed_ms=%" PRIu64 " epoch_ms=%" PRIu64 "\n",
             last_samples, sample & 0xffffU, (sample >> 16) & 0xffU,
             now_ms() - start_ms, epoch_ms());
      fflush(stdout);
    }
    if (st & DONE) break;
    if (interrupted || now_ms() > host_deadline) {
      r[G2_CMD / 4] = 0x47320002U;
      fputs("ERR cancelled_or_host_timeout; a sent motion frame cannot be undone\n",
            stderr);
      goto done;
    }
    pause_ms(5);
  } while (1);

  uint32_t fault = r[G2_FAULT / 4];

  /* 优先用 PL 锁存的故障快照。没有它（旧 PL 读回 0）时回退到当刻读取
   * G1_FAULT/G1_RESULT —— 这两者在 ABI 0D 起就存在，因此板端无需重综合
   * 也能把“超时/坏帧”与“舵机自报 ERROR”区分开。 */
  uint32_t diag = r[G2_DIAG / 4];
  unsigned d_phase = (diag >> 8) & 0xffU;
  unsigned d_axis = (diag >> 4) & 15U;
  unsigned d_servo = (diag >> 16) & 0xffU;
  uint32_t engine_fault, engine_result;
  unsigned raw_error;
  if (d_phase != 0) {
    engine_fault = diag & 15U;
    raw_error = d_servo;
    engine_result = (d_servo << 16) | (r[G2_FEEDBACK / 4] & 65535U);
  } else {
    engine_fault = (fault == 5 || fault == 8) ? (r[G1_FAULT / 4] & 15U) : 0;
    engine_result = (fault == 5 || fault == 8) ? r[G1_RESULT / 4] : 0;
    raw_error = (engine_result >> 16) & 255U;
    d_axis = id;   /* 无锁存时，单轴命令的故障轴就是本次命令的 ID */
  }
  const char *phase_text = d_phase ? diag_phase_name(d_phase)
                                   : motion_phase(fault, st);
  uint64_t done_epoch_ms = epoch_ms(), done_elapsed_ms = now_ms() - start_ms;
  position = r[G2_FEEDBACK / 4] & 65535U;

  printf("result id=%u start=UNAVAILABLE target=%u last=", id, target);
  if (st & FEEDBACK_VALID) printf("%u", position); else printf("UNAVAILABLE");

  printf(" actual_delta=UNAVAILABLE position_change_observed=UNAVAILABLE"
         " target_error=");
  if (st & FEEDBACK_VALID) {
    unsigned error = position > target ? position - target : target - position;
    printf("%u in_band=%u", error, error <= tolerance);
  } else printf("UNAVAILABLE in_band=UNAVAILABLE");

  printf(" write_sent=%u unicast_ack=%u fault=%" PRIu32 " fault_id=%u\n",
         (st & WRITE_SENT) != 0, (st & WRITE_ACK) != 0, fault, id);

  printf("diagnostic phase=%s engine_fault=%" PRIu32 " servo_error_raw=",
         phase_text, engine_fault);
  if (engine_fault == 8) printf("0x%02x", raw_error); else printf("UNAVAILABLE");

  printf(" servo_error_bits=");
  if (engine_fault == 8) print_servo_error_bits(stdout, raw_error);
  else printf("UNAVAILABLE");

  printf(" incident_position=");
  if (engine_fault == 8 && fault == 5) printf("%u", engine_result & 65535U);
  else printf("UNAVAILABLE");

  printf(" incident_position_valid=%u start_valid=%u last_valid=%u"
         " write_started=%u unicast_ack_valid=%u elapsed_ms=%" PRIu64
         " epoch_ms=%" PRIu64 " engine_class=%s engine_reason=%s fault_axis=%u"
         " diag_latched=%u\n",
         engine_fault == 8 && fault == 5, 0U,
         (st & FEEDBACK_VALID) != 0, (st & WRITE_SENT) != 0,
         (st & WRITE_ACK) != 0, done_elapsed_ms, done_epoch_ms,
         engine_fault_class(engine_fault), engine_fault_name(engine_fault),
         d_axis, d_phase != 0);

  if (st & ERROR || fault != 0 || !(st & WRITE_SENT)) {
    fprintf(stderr,
            "ERR g2_fault=%" PRIu32 " fault_id=%u write_sent=%u unicast_ack=%u"
            " position_feedback_valid=%u phase=%s engine_fault=%" PRIu32
            " engine_class=%s engine_reason=%s servo_error_raw=",
            fault, id, (st & WRITE_SENT) != 0, (st & WRITE_ACK) != 0,
            (st & FEEDBACK_VALID) != 0, phase_text, engine_fault,
            engine_fault_class(engine_fault), engine_fault_name(engine_fault));
    if (engine_fault == 8) fprintf(stderr, "0x%02x\n", raw_error);
    else fprintf(stderr, "UNAVAILABLE\n");
    if (!(st & WRITE_SENT)) {
      /* 提交前就失败：这一次没有任何运动帧上线，不能写成“运动失败”。 */
      if (engine_fault == 8)
        fputs("HINT 本次没有发出任何运动帧（write_sent=0）：舵机在回应一条只读 "
              "READ 时自报 ERROR。phase=pre_commit 表示这是发前位置 READ 被该 "
              "ERROR 拦下，运动指令根本没提交——这是读阶段的门禁，不是运动失败。\n",
              stderr);
      else if (engine_fault >= 3 && engine_fault <= 7)
        fputs("HINT 本次没有发出任何运动帧（write_sent=0）：提交前的只读 READ 没能"
              "拿到可信应答，先查总线接线/共地/波特率与舵机供电。\n", stderr);
      else
        fputs("HINT 本次没有发出任何运动帧（write_sent=0）：问题在提交前的检查或"
              "读阶段，与舵机是否肯动无关。\n", stderr);
    } else if (engine_fault >= 3 && engine_fault <= 7) {
      fputs("HINT 运动帧已发出但没拿到一条可信应答（传输层）：先查总线接线/"
            "共地/波特率与舵机供电，这不是舵机参数问题。\n", stderr);
    } else if (engine_fault == 8) {
      fputs("HINT 运动帧已被舵机接受（校验有效），舵机在应答里自报错误："
            "按 ERROR 位与 0x3C 负载 / 0x45 电流 / 0x42 移动标志定因。\n", stderr);
    } else if (fault == 9) {
      fputs("HINT 观察期内未连续三次进入容差带：舵机没走到、没走完，或速度太慢。\n",
            stderr);
    } else if (fault == 16) {
      fputs("HINT fault 16 = 位置已在容差带内但没有观察到位置变化：目标本来就在"
            "当前位置附近，舵机无需运动。这是判定规则产生的假失败，不是运动失败。\n",
            stderr);
    }
    goto done;
  }

  if (!(st & FEEDBACK_VALID) || !(st & WRITE_ACK) ||
      (position > target ? position - target : target - position) > tolerance) {
    fprintf(stderr,
            "ERR incomplete_or_out_of_band_result target=%u position_raw=%u\n",
            target, position);
    goto done;
  }

  printf("RTCS_PL_G2_OK id=%u target=%u position_raw=%u final_error=%u"
         " actual_delta=UNAVAILABLE position_change_observed=UNAVAILABLE"
         " samples=%" PRIu32 " elapsed_ms=%" PRIu64 " timing=%s\n",
         id, target, position,
         position > target ? position - target : target - position,
         (st >> 8) & 0xffU, now_ms() - start_ms,
         st & LATE ? "AFTER_2S" : "WITHIN_2S");

  result = EXIT_SUCCESS;

done:
  munmap(mapping, MAP_BYTES);
  close(fd);
  return result;
}
