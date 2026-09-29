/*
 * G1 BusLinker USB protocol probe for HX-30HM.
 *
 * This is deliberately a read-only Linux baseline.  It sends one single-cast
 * PING or one present-position READ through a BusLinker V3.0 attached to the
 * PS USB host.  It never emits WRITE, REG_WRITE, ACTION, SYNC_WRITE, RESET,
 * broadcast-ID, torque, mode, speed, or position commands.
 *
 * The program proves USB enumeration, 1 Mbps 8N1 transport, and response
 * packet validation.  PL servo_tx_en remains disabled throughout this path.
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
#define HX_ADDR_PRESENT_POSITION 0x38U
#define HX_POSITION_BYTES 2U
#define HX_MAX_RESPONSE_LENGTH 32U
#define HX_BAUD 1000000U
#define UART_FRAME_BITS 10U

typedef enum {
  REQUEST_PING,
  REQUEST_READ_POSITION,
} request_kind;

typedef struct {
  const char *device;
  uint8_t id;
  unsigned timeout_ms;
  request_kind kind;
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
          "[--timeout-ms 1..1000] <ping|read-position>\n"
          "read-only G1 USB baseline; serial format is fixed at 1000000-8N1.\n",
          program);
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

static int parse_args(int argc, char **argv, config_t *config) {
  int index;
  int action_set = 0;
  unsigned id = 0U;
  config->device = NULL;
  config->id = 0U;
  config->timeout_ms = 100U;
  config->kind = REQUEST_PING;

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
    } else if (strcmp(argv[index], "ping") == 0) {
      config->kind = REQUEST_PING;
      action_set = 1;
    } else if (strcmp(argv[index], "read-position") == 0) {
      config->kind = REQUEST_READ_POSITION;
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

  frame[0] = HX_FRAME_HEADER;
  frame[1] = HX_FRAME_HEADER;
  frame[2] = config.id;
  if (config.kind == REQUEST_PING) {
    frame[3] = 2U;
    frame[4] = HX_INST_PING;
    frame[5] = checksum(&frame[2], 3U);
    frame_length = 6U;
  } else {
    frame[3] = 4U;
    frame[4] = HX_INST_READ;
    frame[5] = HX_ADDR_PRESENT_POSITION;
    frame[6] = HX_POSITION_BYTES;
    frame[7] = checksum(&frame[2], 5U);
    frame_length = 8U;
  }

  printf("RTCS_BUSLINKER_G1_START device=%s baud=%u format=8N1 flow_control=none "
         "theoretical_bytes_per_second=%u id=%u command=%s\n",
         config.device, HX_BAUD, HX_BAUD / UART_FRAME_BITS, config.id,
         config.kind == REQUEST_PING ? "PING" : "READ_PRESENT_POSITION");
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
