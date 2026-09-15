/*
 * RTCS 串口回环工具（serial loopback）
 *
 * 用途：在 G1 前独立验证 PS 侧 UART 数据通路。程序打开一个由命令行指定的串口，
 * 把从该串口收到的字节原样写回。它只适用于独立的测试 UART：外部测试端
 * 发送字节，目标 UART 回写，测试端接收。不要把同一 UART 的 TX/RX 物理短接，
 * 否则透明回显会再次接收到自身发送的数据而形成重复回显。
 *
 * 安全边界：
 *   - --device 必填，且不得与 stdin/stdout 所属控制台是同一个终端设备；
 *     因此不会抢占 PS UART1 登录控制台。绝不映射任何 UIO/MMIO。
 *   - 纯用户态 termios，与 PL 内部硬性禁用的 servo_tx_en 无关。
 *
 * 协议：无。收到什么就回什么（字节级透明回显）。以 SIGINT/SIGTERM 退出。
 */

/* 在 -std=c11 下显式启用 POSIX 接口（clock_gettime、sigaction、select 等）。 */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif

#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#error "rtcs_uart_loopback 依赖 POSIX termios，只能在目标 Linux 上交叉编译运行"
#endif

#include <fcntl.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>

#define RTCS_LOOPBACK_DEFAULT_BAUD 115200U
#define RTCS_LOOPBACK_UART_FRAME_BITS 10U
#define RTCS_LOOPBACK_IO_CHUNK 256U
#define RTCS_LOOPBACK_STATS_PERIOD_NS 1000000000ULL

/* 命令行解析结果。 */
typedef struct {
  const char *device;
  unsigned baud;
} loopback_config;

static volatile sig_atomic_t stop_requested;

static void request_stop(int signal_number) {
  (void)signal_number;
  stop_requested = 1;
}

static uint64_t monotonic_ns(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

/* 把数值波特率映射为 termios 常量；不支持的速率返回 B0 以便调用方报错。 */
static speed_t baud_to_speed(unsigned baud) {
  switch (baud) {
    case 9600U: return B9600;
    case 19200U: return B19200;
    case 38400U: return B38400;
    case 57600U: return B57600;
    case 115200U: return B115200;
    case 230400U: return B230400;
    case 460800U: return B460800;
    case 921600U: return B921600;
    default: return B0;
  }
}

static void print_usage(const char *program) {
  fprintf(stderr,
          "usage: %s --device PATH [--baud RATE]\n"
          "  --device PATH  required independent serial device (not stdin/stdout terminal)\n"
          "  --baud RATE    9600/19200/38400/57600/115200/230400/460800/921600"
          " (default %u)\n",
          program, RTCS_LOOPBACK_DEFAULT_BAUD);
}

/* 解析参数；成功返回 0，请求 usage/错误返回非 0。 */
static int parse_args(int argc, char **argv, loopback_config *config) {
  config->device = NULL;
  config->baud = RTCS_LOOPBACK_DEFAULT_BAUD;

  for (int i = 1; i < argc; ++i) {
    if (strcmp(argv[i], "--device") == 0 && i + 1 < argc) {
      config->device = argv[++i];
    } else if (strcmp(argv[i], "--baud") == 0 && i + 1 < argc) {
      char *end;
      unsigned long parsed;
      errno = 0;
      parsed = strtoul(argv[++i], &end, 10);
      if (errno != 0 || *end != '\0' || parsed == 0UL || parsed > UINT32_MAX) {
        fprintf(stderr, "ERR invalid_baud %s\n", argv[i]);
        return 1;
      }
      config->baud = (unsigned)parsed;
    } else {
      print_usage(argv[0]);
      return 1;
    }
  }
  if (config->device == NULL) {
    fprintf(stderr, "ERR missing_device\n");
    print_usage(argv[0]);
    return 1;
  }
  return 0;
}

/* True only when PATH resolves to the same character device as FD's terminal. */
static int device_matches_terminal(const char *path, int fd) {
  struct stat device_stat;
  struct stat terminal_stat;

  if (!isatty(fd)) return 0;
  if (stat(path, &device_stat) != 0 || fstat(fd, &terminal_stat) != 0) return 0;
  return S_ISCHR(device_stat.st_mode) && S_ISCHR(terminal_stat.st_mode) &&
         device_stat.st_rdev == terminal_stat.st_rdev;
}

/* 以 raw 8N1、无流控方式打开并配置串口；失败返回 -1。 */
static int open_serial(const loopback_config *config) {
  int fd;
  struct termios tio;
  speed_t speed = baud_to_speed(config->baud);

  if (speed == B0) {
    fprintf(stderr, "ERR unsupported_baud %u\n", config->baud);
    return -1;
  }

  fd = open(config->device, O_RDWR | O_NOCTTY | O_NONBLOCK);
  if (fd < 0) {
    fprintf(stderr, "ERR open_failed %s: %s\n", config->device, strerror(errno));
    return -1;
  }

  if (tcgetattr(fd, &tio) != 0) {
    fprintf(stderr, "ERR tcgetattr: %s\n", strerror(errno));
    close(fd);
    return -1;
  }

  cfmakeraw(&tio);          /* 8 位、无回显、无信号、无行处理，字节级透明 */
  tio.c_cflag &= (tcflag_t)~(PARENB | CSTOPB | CRTSCTS); /* 8N1、无硬件流控 */
  tio.c_cflag |= (CLOCAL | CREAD);                       /* 忽略调制解调器线，允许接收 */
  tio.c_iflag &= (tcflag_t)~(IXON | IXOFF | IXANY);      /* 无软件流控 */
  tio.c_cc[VMIN] = 0;       /* 配合非阻塞与 select，read 立即返回 */
  tio.c_cc[VTIME] = 0;

  if (cfsetispeed(&tio, speed) != 0 || cfsetospeed(&tio, speed) != 0) {
    fprintf(stderr, "ERR cfsetspeed: %s\n", strerror(errno));
    close(fd);
    return -1;
  }
  if (tcsetattr(fd, TCSANOW, &tio) != 0) {
    fprintf(stderr, "ERR tcsetattr: %s\n", strerror(errno));
    close(fd);
    return -1;
  }
  tcflush(fd, TCIOFLUSH);
  return fd;
}

/* 把整块缓冲全部写出，处理非阻塞下的部分写与 EAGAIN。 */
static int write_all(int fd, const uint8_t *data, size_t length) {
  size_t written = 0;
  while (written < length) {
    ssize_t n = write(fd, data + written, length - written);
    if (n < 0) {
      if (errno == EINTR) continue;
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        fd_set writable;
        int ready;
        FD_ZERO(&writable);
        FD_SET(fd, &writable);
        ready = select(fd + 1, NULL, &writable, NULL, NULL);
        if (ready >= 0 || errno == EINTR) continue;
      }
      return -1;
    }
    written += (size_t)n;
  }
  return 0;
}

static void print_banner(const loopback_config *config) {
  printf("RTCS_UART_LOOPBACK_OK\n");
  printf("device=%s baud=%u format=8N1 flow_control=none\n", config->device,
         config->baud);
  printf("uart_theoretical_bytes_per_second=%u\n",
         config->baud / RTCS_LOOPBACK_UART_FRAME_BITS);
  printf("mode=byte-transparent echo; stop with SIGINT or SIGTERM\n");
  fflush(stdout);
}

static void print_stats(uint64_t now, uint64_t started, uint64_t rx_total,
                        uint64_t tx_total) {
  double elapsed = (double)(now - started) / 1e9;
  double rx_bps = elapsed > 0.0 ? (double)rx_total / elapsed : 0.0;
  double tx_bps = elapsed > 0.0 ? (double)tx_total / elapsed : 0.0;
  printf("STATS rx_bytes=%" PRIu64 " tx_bytes=%" PRIu64
         " rx_bps=%.1f tx_bps=%.1f\n",
         rx_total, tx_total, rx_bps, tx_bps);
  fflush(stdout);
}

int main(int argc, char **argv) {
  loopback_config config;
  int fd;
  struct sigaction action;
  uint64_t started;
  uint64_t last_stats;
  uint64_t rx_total = 0;
  uint64_t tx_total = 0;

  if (parse_args(argc, argv, &config) != 0) return EXIT_FAILURE;
  if (device_matches_terminal(config.device, STDIN_FILENO) ||
      device_matches_terminal(config.device, STDOUT_FILENO)) {
    fprintf(stderr, "ERR console_device_conflict %s\n", config.device);
    return EXIT_FAILURE;
  }

  memset(&action, 0, sizeof action);
  action.sa_handler = request_stop;
  sigemptyset(&action.sa_mask);
  if (sigaction(SIGINT, &action, NULL) != 0 || sigaction(SIGTERM, &action, NULL) != 0) {
    fprintf(stderr, "ERR signal_setup: %s\n", strerror(errno));
    return EXIT_FAILURE;
  }

  fd = open_serial(&config);
  if (fd < 0) return EXIT_FAILURE;

  print_banner(&config);
  started = monotonic_ns();
  last_stats = started;

  while (!stop_requested) {
    fd_set readable;
    struct timeval wait;
    uint64_t now;
    int ready;

    FD_ZERO(&readable);
    FD_SET(fd, &readable);
    wait.tv_sec = 1;
    wait.tv_usec = 0;

    ready = select(fd + 1, &readable, NULL, NULL, &wait);
    if (ready < 0) {
      if (errno == EINTR) continue;
      fprintf(stderr, "ERR select: %s\n", strerror(errno));
      close(fd);
      return EXIT_FAILURE;
    }

    now = monotonic_ns();

    if (ready > 0 && FD_ISSET(fd, &readable)) {
      uint8_t buffer[RTCS_LOOPBACK_IO_CHUNK];
      ssize_t got = read(fd, buffer, sizeof buffer);
      if (got < 0) {
        if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) {
          fprintf(stderr, "ERR read: %s\n", strerror(errno));
          close(fd);
          return EXIT_FAILURE;
        }
      } else if (got > 0) {
        rx_total += (uint64_t)got;
        if (write_all(fd, buffer, (size_t)got) != 0) {
          fprintf(stderr, "ERR write: %s\n", strerror(errno));
          close(fd);
          return EXIT_FAILURE;
        }
        tx_total += (uint64_t)got;
      }
    }

    if (now - last_stats >= RTCS_LOOPBACK_STATS_PERIOD_NS) {
      print_stats(now, started, rx_total, tx_total);
      last_stats = now;
    }
  }

  print_stats(monotonic_ns(), started, rx_total, tx_total);
  puts("RTCS_UART_LOOPBACK_EXIT");
  fflush(stdout);
  close(fd);
  return EXIT_SUCCESS;
}
