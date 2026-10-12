/* G1 PL/UIO read-only control. No USB forwarding and no motion opcodes. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/file.h>
#include <time.h>
#include <unistd.h>

enum { REGION_BYTES = 0x10000, ID_VERSION = 0x5254000e,
       REG_ID = 0x00, REG_G1_ID = 0x50, REG_G1_OP = 0x54,
       REG_G1_CMD = 0x58, REG_G1_STATUS = 0x5c,
       REG_G1_RESULT = 0x60, REG_G1_FAULT = 0x64 };
enum { STATUS_BUSY = 1, STATUS_DONE = 2, STATUS_ERROR = 4,
       STATUS_TX_DISABLED = 8 };

static uint64_t monotonic_ms(void) {
  struct timespec now;
  if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return 0;
  return (uint64_t)now.tv_sec * 1000U + (uint64_t)now.tv_nsec / 1000000U;
}

static void usage(const char *program) {
  fprintf(stderr, "usage: %s --uio /dev/uio<N> [--id 1..253] <probe|ping|read-position>\n", program);
}

int main(int argc, char **argv) {
  const char *uio = NULL;
  unsigned id = 0;
  int operation = 0;
  int fd;
  void *mapping;
  volatile uint32_t *regs;
  uint32_t status;
  uint64_t deadline;
  struct timespec pause_time = {0, 1000000};

  for (int i = 1; i < argc; ++i) {
    if (!strcmp(argv[i], "--uio") && i + 1 < argc) uio = argv[++i];
    else if (!strcmp(argv[i], "--id") && i + 1 < argc) {
      char *end = NULL;
      unsigned long value;
      errno = 0;
      value = strtoul(argv[++i], &end, 10);
      if (errno || end == argv[i] || *end || value < 1 || value > 253) {
        fputs("ERR invalid_id\n", stderr); return EXIT_FAILURE;
      }
      id = (unsigned)value;
    } else if (!strcmp(argv[i], "probe")) operation = -1;
    else if (!strcmp(argv[i], "ping")) operation = 1;
    else if (!strcmp(argv[i], "read-position")) operation = 2;
    else { usage(argv[0]); return EXIT_FAILURE; }
  }
  if (!uio || !operation || (operation > 0 && !id)) {
    usage(argv[0]); return EXIT_FAILURE;
  }
  fd = open(uio, O_RDWR | O_SYNC);
  if (fd < 0) { perror("ERR open_uio"); return EXIT_FAILURE; }
  if (flock(fd, LOCK_EX | LOCK_NB) != 0) {
    perror("ERR bus_locked"); close(fd); return EXIT_FAILURE;
  }
  mapping = mmap(NULL, REGION_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (mapping == MAP_FAILED) { perror("ERR mmap_uio"); close(fd); return EXIT_FAILURE; }
  regs = (volatile uint32_t *)mapping;
  if (regs[REG_ID / 4] != ID_VERSION) {
    fprintf(stderr, "ERR incompatible_pl_id 0x%08" PRIx32 " expected=0x%08x\n",
            regs[REG_ID / 4], ID_VERSION);
    munmap(mapping, REGION_BYTES); close(fd); return EXIT_FAILURE;
  }
  status = regs[REG_G1_STATUS / 4];
  printf("RTCS_PL_G1 board=AX7Z020B id_version=0x%08x status=0x%08" PRIx32
         " physical_tx=%s\n", ID_VERSION, status,
         (status & STATUS_TX_DISABLED) ? "DISABLED" : "ENABLED");
  if (operation == -1) { munmap(mapping, REGION_BYTES); close(fd); return EXIT_SUCCESS; }
  if (status & STATUS_TX_DISABLED) {
    fputs("ERR physical_tx_disabled; check J20-36 to J20-38 inhibit strap\n", stderr);
    munmap(mapping, REGION_BYTES); close(fd); return EXIT_FAILURE;
  }
  if (status & STATUS_BUSY) {
    fputs("ERR pl_busy\n", stderr);
    munmap(mapping, REGION_BYTES); close(fd); return EXIT_FAILURE;
  }
  regs[REG_G1_CMD / 4] = 2; /* clear previous result */
  __sync_synchronize();
  regs[REG_G1_ID / 4] = id;
  regs[REG_G1_OP / 4] = (unsigned)operation;
  __sync_synchronize();
  regs[REG_G1_CMD / 4] = 1; /* final atomic commit */
  deadline = monotonic_ms() + 300;
  do {
    status = regs[REG_G1_STATUS / 4];
    if (status & STATUS_TX_DISABLED) {
      fputs("ERR physical_tx_inhibited_during_command\n", stderr);
      munmap(mapping, REGION_BYTES); close(fd); return EXIT_FAILURE;
    }
    if (status & STATUS_DONE) break;
    nanosleep(&pause_time, NULL);
  } while (monotonic_ms() < deadline);
  if (!(status & STATUS_DONE)) {
    regs[REG_G1_CMD / 4] = 2;
    fputs("ERR host_wait_timeout\n", stderr);
    munmap(mapping, REGION_BYTES); close(fd); return EXIT_FAILURE;
  }
  if (status & STATUS_ERROR) {
    fprintf(stderr, "ERR pl_fault=%" PRIu32 "\n", regs[REG_G1_FAULT / 4]);
    munmap(mapping, REGION_BYTES); close(fd); return EXIT_FAILURE;
  }
  {
    uint32_t result = regs[REG_G1_RESULT / 4];
    if ((result >> 16) & 0xffU) {
      fprintf(stderr, "ERR servo_error=0x%02" PRIx32 "\n", (result >> 16) & 0xffU);
      munmap(mapping, REGION_BYTES); close(fd); return EXIT_FAILURE;
    }
    if (operation == 2) printf("position_raw=%" PRIu32 "\n", result & 0xffffU);
  }
  printf("RTCS_PL_G1_OK id=%u command=%s\n", id, operation == 1 ? "PING" : "READ_POSITION");
  munmap(mapping, REGION_BYTES);
  close(fd);
  return EXIT_SUCCESS;
}
