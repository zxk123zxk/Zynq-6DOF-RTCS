/*
 * RTCS 串口回环工具（serial loopback）
 *
 * 用途：在 G1 前独立验证 PS 侧 UART 数据通路。程序打开一个由命令行指定的串口，
 * 把从该串口收到的字节原样写回。可配合物理短接（TX↔RX）做本地自回环，
 * 也可与主机串口对拷做双机回环。
 *
 * 安全边界：
 *   - 串口设备与波特率均由参数给出，默认 /dev/ttyPS1（PS 调试 UART1），
 *     绝不默认触碰 1 Mbps 半双工舵机总线，也不映射任何 UIO/MMIO。
 *   - 纯用户态 termios，与 PL 内部硬性禁用的 servo_tx_en 无关。
 *
 * 协议：无。收到什么就回什么（字节级透明回环）。stdin 输入 quit 可退出。
 */

/* 在 -std=c11 下显式启用 POSIX 接口（clock_gettime、cfmakeraw、select 等）。 */
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif

#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
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
#include <termios.h>
#include <unistd.h>

#define RTCS_LOOPBACK_DEFAULT_DEVICE "/dev/ttyPS1"
#define RTCS_LOOPBACK_DEFAULT_BAUD 115200U
#define RTCS_LOOPBACK_UART_FRAME_BITS 10U
#define RTCS_LOOPBACK_IO_CHUNK 256U
#define RTCS_LOOPBACK_STATS_PERIOD_NS 1000000000ULL

/* 命令行解析结果。 */
typedef struct {
  const char *device;
  unsigned baud;
} loopback_config;

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
          "usage: %s [--device PATH] [--baud RATE]\n"
          "  --device PATH  serial device (default %s)\n"
          "  --baud RATE    9600/19200/38400/57600/115200/230400/460800/921600"
          " (default %u)\n",
          program, RTCS_LOOPBACK_DEFAULT_DEVICE, RTCS_LOOPBACK_DEFAULT_BAUD);
}

/* 解析参数；成功返回 0，请求 usage/错误返回非 0。 */
static int parse_args(int argc, char **argv, loopback_config *config) {
  config->device = RTCS_LOOPBACK_DEFAULT_DEVICE;
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
  return 0;
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
      if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) continue;
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
  printf("mode=byte-transparent echo; type quit on stdin to exit\n");
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

/* 读取 stdin 一行，判断是否为退出命令。返回 1 表示应退出。 */
static int stdin_requests_quit(void) {
  char line[64];
  char *cursor;
  char *end;
  if (fgets(line, sizeof line, stdin) == NULL) return 1; /* EOF 视为退出 */

  cursor = line;
  while (isspace((unsigned char)*cursor)) ++cursor;
  end = cursor + strlen(cursor);
  while (end > cursor && isspace((unsigned char)end[-1])) --end;
  *end = '\0';
  return strcmp(cursor, "quit") == 0;
}

int main(int argc, char **argv) {
  loopback_config config;
  int fd;
  uint64_t started;
  uint64_t last_stats;
  uint64_t rx_total = 0;
  uint64_t tx_total = 0;

  if (parse_args(argc, argv, &config) != 0) return EXIT_FAILURE;

  fd = open_serial(&config);
  if (fd < 0) return EXIT_FAILURE;

  print_banner(&config);
  started = monotonic_ns();
  last_stats = started;

  for (;;) {
    fd_set readable;
    struct timeval wait;
    uint64_t now;
    int max_fd = fd > STDIN_FILENO ? fd : STDIN_FILENO;
    int ready;

    FD_ZERO(&readable);
    FD_SET(fd, &readable);
    FD_SET(STDIN_FILENO, &readable);
    wait.tv_sec = 1;
    wait.tv_usec = 0;

    ready = select(max_fd + 1, &readable, NULL, NULL, &wait);
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

    if (ready > 0 && FD_ISSET(STDIN_FILENO, &readable)) {
      if (stdin_requests_quit()) {
        print_stats(now, started, rx_total, tx_total);
        puts("RTCS_UART_LOOPBACK_EXIT");
        fflush(stdout);
        close(fd);
        return EXIT_SUCCESS;
      }
    }

    if (now - last_stats >= RTCS_LOOPBACK_STATS_PERIOD_NS) {
      print_stats(now, started, rx_total, tx_total);
      last_stats = now;
    }
  }
}
