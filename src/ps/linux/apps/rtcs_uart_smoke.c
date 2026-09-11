#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifndef _WIN32
#include <sys/select.h>
#include <unistd.h>
#endif

#define RTCS_UART_BAUD 115200U
#define RTCS_UART_FRAME_BITS 10U
#define RTCS_PL_CLOCK_HZ 100000000U
#define RTCS_AXI_BASE 0x43C00000U
#define RTCS_TARGET_LINES_PER_SECOND 100U
#define RTCS_LINE_CAPACITY 64U

static uint64_t monotonic_ns(void) {
#ifdef _WIN32
  return (uint64_t)clock() * 1000000000ULL / (uint64_t)CLOCKS_PER_SEC;
#else
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
#endif
}

static char *trim(char *text) {
  char *end;
  while (isspace((unsigned char)*text)) ++text;
  end = text + strlen(text);
  while (end > text && isspace((unsigned char)end[-1])) --end;
  *end = '\0';
  return text;
}

static void print_banner(void) {
  printf("RTCS_G0_OK\n");
  printf("board=AX7Z020B uart=/dev/ttyPS1 format=115200-8N1 flow_control=none\n");
  printf("pl_clock_hz=%u axi_base=0x%08X\n", RTCS_PL_CLOCK_HZ, RTCS_AXI_BASE);
  printf("uart_theoretical_payload_bytes_per_second=%u target_input_lines_per_second=%u\n",
         RTCS_UART_BAUD / RTCS_UART_FRAME_BITS, RTCS_TARGET_LINES_PER_SECOND);
  printf("protocol=one signed 32-bit decimal per line; reply is OK value_plus_one; type quit to exit\n");
  fflush(stdout);
}

static void print_stats(uint64_t now, uint64_t started, uint64_t last, uint64_t total, uint64_t previous) {
  const double elapsed = (double)(now - started) / 1e9;
  const double interval = (double)(now - last) / 1e9;
  const double average_hz = elapsed > 0.0 ? (double)total / elapsed : 0.0;
  const double interval_hz = interval > 0.0 ? (double)(total - previous) / interval : 0.0;
  printf("STATS lines_total=%" PRIu64 " average_hz=%.2f interval_hz=%.2f\n",
         total, average_hz, interval_hz);
  fflush(stdout);
}

int main(void) {
  char line[RTCS_LINE_CAPACITY];
  uint64_t started = monotonic_ns();
  uint64_t last_stats = started;
  uint64_t total_lines = 0;
  uint64_t previous_lines = 0;

  print_banner();
  for (;;) {
    char *input;
    char *end;
    long value;
    uint64_t now;

#ifndef _WIN32
    fd_set readable;
    struct timeval wait;
    uint64_t until_stats = 1000000000ULL - (monotonic_ns() - last_stats);
    if (until_stats > 1000000000ULL) until_stats = 0;
    FD_ZERO(&readable);
    FD_SET(STDIN_FILENO, &readable);
    wait.tv_sec = (time_t)(until_stats / 1000000000ULL);
    wait.tv_usec = (suseconds_t)((until_stats % 1000000000ULL) / 1000ULL);
    if (select(STDIN_FILENO + 1, &readable, NULL, NULL, &wait) < 0) {
      perror("select");
      return EXIT_FAILURE;
    }
    now = monotonic_ns();
    if (!FD_ISSET(STDIN_FILENO, &readable)) {
      print_stats(now, started, last_stats, total_lines, previous_lines);
      previous_lines = total_lines;
      last_stats = now;
      continue;
    }
#endif
    if (fgets(line, sizeof line, stdin) == NULL) break;
    now = monotonic_ns();
    if (now - last_stats >= 1000000000ULL) {
      print_stats(now, started, last_stats, total_lines, previous_lines);
      previous_lines = total_lines;
      last_stats = now;
    }
    if (strchr(line, '\n') == NULL && !feof(stdin)) {
      int ch;
      while ((ch = getchar()) != '\n' && ch != EOF) { }
      puts("ERR line_too_long");
      fflush(stdout);
      continue;
    }

    input = trim(line);
    if (*input == '\0') {
      puts("ERR empty_input");
      fflush(stdout);
      continue;
    }
    if (strcmp(input, "quit") == 0) {
      puts("RTCS_UART_SMOKE_EXIT");
      fflush(stdout);
      return EXIT_SUCCESS;
    }

    errno = 0;
    value = strtol(input, &end, 10);
    if (errno == ERANGE || end == input || *trim(end) != '\0' ||
        value < INT32_MIN || value > INT32_MAX) {
      puts("ERR invalid_signed_32_bit_decimal");
    } else if (value == INT32_MAX) {
      puts("ERR increment_overflow");
    } else {
      printf("OK %ld\n", value + 1L);
      ++total_lines;
    }
    fflush(stdout);
  }
  puts("RTCS_UART_SMOKE_EOF");
  return EXIT_SUCCESS;
}
