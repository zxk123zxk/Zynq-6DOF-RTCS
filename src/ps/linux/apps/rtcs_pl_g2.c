/* ID 1..6 G2 motion. Each explicit command sends at most one motion frame.
 *
 * ABI 12 retains the 0x28..0x2F atomic motion frame, so the torque
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

enum { MAP_BYTES=0x10000, ABI=0x5254000c,
  ID=0x00, TICKS_LO=0x14, TICKS_HI=0x18,
  G1_ID=0x50, G1_OP=0x54, G1_CMD=0x58, G1_STATUS=0x5c,
  G1_RESULT=0x60, G1_FAULT=0x64,
  G2_ID=0x68, G2_TOLERANCE_OBSERVE=0x6c,
  G2_TARGET=0x70, G2_SPEED_TIME=0x74,
  G2_DEADLINE_LO=0x78, G2_DEADLINE_HI=0x7c, G2_CMD=0x80,
  G2_STATUS=0x84, G2_FAULT=0x88, G2_FEEDBACK=0x8c,
  CAL_MASK=0xd8, LIMIT_ID=0xec, LIMIT_MIN=0xf0,
  LIMIT_MAX=0xf4, LIMIT_REFERENCE=0xf8, LIMIT_SPEED_MAX=0xfc,
  G2_START=0x114,
  BUSY=1, DONE=2, ERROR=4, INHIBITED=8, WRITE_SENT=16,
  LATE=32, START_VALID=64, FEEDBACK_VALID=128,
  WRITE_ACK=65536, POSITION_CHANGED=131072, OP_TORQUE_OFF=9 };
static volatile sig_atomic_t interrupted;
static void on_signal(int sig) { (void)sig; interrupted=1; }
static uint64_t now_ms(void) {
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC,&t)) return 0;
  return (uint64_t)t.tv_sec*1000 + (uint64_t)t.tv_nsec/1000000;
}
static void pause_ms(unsigned ms) {
  struct timespec t={ms/1000U,(long)(ms%1000U)*1000000L};
  while (nanosleep(&t,&t) && errno==EINTR && !interrupted) {}
}
static int parse_uint(const char *s, unsigned *out) {
  char *end=NULL; unsigned long v;
  if (!s || !*s || *s=='-' || *s=='+') return -1;
  errno=0; v=strtoul(s,&end,10);
  if (errno || !end || *end || v>UINT32_MAX) return -1;
  *out=(unsigned)v; return 0;
}
static uint64_t ticks(volatile uint32_t *r) {
  uint32_t hi,lo,hi2;
  do { hi=r[TICKS_HI/4]; lo=r[TICKS_LO/4]; hi2=r[TICKS_HI/4]; } while (hi!=hi2);
  return ((uint64_t)hi<<32)|lo;
}
/* Runs one G1-path command and returns its PL fault code, or -1 on transport
 * failure. Only OP_READ and OP_TORQUE_OFF pass the PL whitelist; any opcode
 * that can write a position is refused by the PL with fault 13. */
static int g1_command(volatile uint32_t *r, unsigned id, unsigned op,
                      unsigned *result) {
  uint64_t deadline;
  uint32_t st;
  if (r[G1_STATUS/4] & (BUSY|INHIBITED)) return -1;
  r[G1_CMD/4]=2; __sync_synchronize();
  r[G1_ID/4]=id; r[G1_OP/4]=op; __sync_synchronize();
  r[G1_CMD/4]=1;
  deadline=now_ms()+300;
  do {
    st=r[G1_STATUS/4];
    if (st&INHIBITED || interrupted) { r[G1_CMD/4]=2; return -1; }
    if (st&DONE) {
      if (st&ERROR) return (int)r[G1_FAULT/4];
      *result=r[G1_RESULT/4];
      return 0;
    }
    pause_ms(1);
  } while (now_ms()<deadline);
  r[G1_CMD/4]=2;
  fputs("ERR g1_host_wait_timeout\n",stderr);
  return -1;
}
static void usage(const char *p) {
  fprintf(stderr,"usage: %s --uio /dev/uioN probe\n"
    "       %s --uio /dev/uioN release --id 1 --execute\n"
    "       %s --uio /dev/uioN move --id 1..6 --target N "
    "--speed-raw N --time-raw N [--tolerance 1..100]"
    " [--observe-ms 1000..10000] --execute\n",p,p,p);
}
int main(int argc,char **argv) {
  const char *path=NULL;
  int probe=0,move=0,release=0,execute=0,fd;
  unsigned id=0,target=0,speed_raw=0,time_raw=0,position=0;
  unsigned tolerance=30,observe_ms=5000;
  int seen_id=0,seen_target=0,seen_speed=0,seen_time=0,seen_tol=0,seen_observe=0;
  volatile uint32_t *r; void *mapping; uint32_t st=0,last_samples=0;
  uint64_t host_deadline,deadline_ticks,start_ms; int result=EXIT_FAILURE;
  for (int i=1;i<argc;i++) {
    if (!strcmp(argv[i],"--uio") && i+1<argc) path=argv[++i];
    else if (!strcmp(argv[i],"--id") && i+1<argc) seen_id++, seen_id+=parse_uint(argv[++i],&id)!=0;
    else if (!strcmp(argv[i],"--target") && i+1<argc) seen_target++, seen_target+=parse_uint(argv[++i],&target)!=0;
    else if (!strcmp(argv[i],"--speed-raw") && i+1<argc) seen_speed++, seen_speed+=parse_uint(argv[++i],&speed_raw)!=0;
    else if (!strcmp(argv[i],"--time-raw") && i+1<argc) seen_time++, seen_time+=parse_uint(argv[++i],&time_raw)!=0;
    else if (!strcmp(argv[i],"--tolerance") && i+1<argc)
      seen_tol++, seen_tol+=parse_uint(argv[++i],&tolerance)!=0;
    else if (!strcmp(argv[i],"--observe-ms") && i+1<argc)
      seen_observe++, seen_observe+=parse_uint(argv[++i],&observe_ms)!=0;
    else if (!strcmp(argv[i],"--execute")) execute++;
    else if (!strcmp(argv[i],"probe")) probe++;
    else if (!strcmp(argv[i],"move") || !strcmp(argv[i],"move-one")) move++;
    else if (!strcmp(argv[i],"release")) release++;
    else { usage(argv[0]); return EXIT_FAILURE; }
  }
  if (!path || (probe+move+release)!=1 || execute>1 || seen_tol>1 || seen_observe>1 ||
      tolerance<1 || tolerance>100 || observe_ms<1000 ||
      observe_ms>10000 || observe_ms%100 ||
      (probe && (seen_id || execute ||
      seen_target || seen_speed || seen_time || seen_tol || seen_observe)) ||
      (move+release>0 && (seen_id!=1 || !execute)) ||
      (release && (seen_target || seen_speed || seen_time || seen_tol || seen_observe)) ||
      (move && (seen_target!=1 || seen_speed!=1 || seen_time!=1))) {
    usage(argv[0]); return EXIT_FAILURE;
  }
  if (move && (id<1 || id>6 || target>UINT16_MAX || speed_raw>UINT16_MAX ||
               time_raw>UINT16_MAX)) {
    fputs("ERR ID must be 1..6 and target/speed-raw/time-raw must fit 16 bits\n",stderr);
    return EXIT_FAILURE;
  }
  if (release && id!=1) {
    fputs("ERR only ID 1 torque release is accepted\n",stderr);
    return EXIT_FAILURE;
  }
  fd=open(path,O_RDWR|O_SYNC);
  if (fd<0) { perror("ERR open_uio (use sudo)"); return EXIT_FAILURE; }
  if (flock(fd,LOCK_EX|LOCK_NB)) { perror("ERR bus_locked"); close(fd); return EXIT_FAILURE; }
  mapping=mmap(NULL,MAP_BYTES,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
  if (mapping==MAP_FAILED) { perror("ERR mmap_uio"); close(fd); return EXIT_FAILURE; }
  r=(volatile uint32_t *)mapping;
  if (r[ID/4]!=ABI) {
    fprintf(stderr,"ERR incompatible_pl_id=0x%08" PRIx32 " expected=0x%08x\n",r[ID/4],ABI);
    goto done;
  }
  st=r[G1_STATUS/4];
  printf("RTCS_PL_G2 board=AX7Z020B abi=0x%08x physical_tx=%s\n",ABI,
    st&INHIBITED?"DISABLED":"ENABLED");
  if (probe) { result=EXIT_SUCCESS; goto done; }
  if (st&(BUSY|INHIBITED)) { fputs("ERR busy_or_inhibited\n",stderr); goto done; }
  signal(SIGINT,on_signal); signal(SIGTERM,on_signal);

  /* 卸力：只写 0x28<-0，不写目标位置，可重复执行。 */
  if (release) {
    int code=g1_command(r,id,OP_TORQUE_OFF,&position);
    if (code<0) { fputs("ERR release_transport\n",stderr); goto done; }
    if (code!=0) { fprintf(stderr,"ERR release_fault=%d\n",code); goto done; }
    if ((position>>16)&0xffU) {
      fprintf(stderr,"ERR release_servo_error=0x%02" PRIx32 "\n",(position>>16)&0xffU);
      goto done;
    }
    printf("RTCS_PL_G2_RELEASE id=%u torque=OFF torque_register=0x28 value=0\n",id);
    result=EXIT_SUCCESS;
    goto done;
  }

  if (!(r[CAL_MASK/4] & (1U<<(id-1)))) {
    fprintf(stderr,"ERR axis_uncalibrated id=%u\n",id); goto done;
  }
  r[LIMIT_ID/4]=id; __sync_synchronize();
  unsigned lo=r[LIMIT_MIN/4], hi=r[LIMIT_MAX/4];
  unsigned reference=r[LIMIT_REFERENCE/4], speed_max=r[LIMIT_SPEED_MAX/4];
  if (r[LIMIT_ID/4]!=id || lo>reference || reference>hi || hi>UINT16_MAX ||
      speed_max!=1500) {
    fprintf(stderr,"ERR invalid_pl_limit id=%u\n",id); goto done;
  }
  if (target<lo || target>hi || speed_raw==0 || speed_raw>speed_max) {
    fprintf(stderr,"ERR target_or_speed_outside_pl_limit id=%u target=%u"
                   " speed_raw=%u range=%u..%u speed_max=%u\n",
            id,target,speed_raw,lo,hi,speed_max);
    goto done;
  }

  if (r[G2_STATUS/4]&BUSY || r[G1_STATUS/4]&INHIBITED || interrupted) {
    fputs("ERR changed_before_commit\n",stderr); goto done;
  }
  r[G2_ID/4]=id; r[G2_TARGET/4]=target;
  r[G2_SPEED_TIME/4]=(time_raw<<16)|speed_raw;
  r[G2_TOLERANCE_OBSERVE/4]=((observe_ms/100)<<16)|tolerance;
  deadline_ticks=ticks(r)+200000000ULL; /* 2 s command deadline at 100 MHz */
  r[G2_DEADLINE_LO/4]=(uint32_t)deadline_ticks;
  r[G2_DEADLINE_HI/4]=(uint32_t)(deadline_ticks>>32);
  __sync_synchronize();
  printf("commit id=%u target=%u speed_raw=%u time_raw=%u"
         " tolerance=%u observe_ms=%u torque_toggle=0x28:1"
         " command_deadline_ticks=%" PRIu64 "\n",
    id,target,speed_raw,time_raw,tolerance,observe_ms,deadline_ticks);
  fflush(stdout);
  start_ms=now_ms();
  r[G2_CMD/4]=0x47320001U;
  host_deadline=start_ms+13000; /* <=2 s before WRITE + <=10 s PL observation + margin */
  do {
    st=r[G2_STATUS/4];
    if (((st>>8)&0xffU)!=last_samples) {
      last_samples=(st>>8)&0xffU;
      printf("sample=%" PRIu32 " position_raw=%" PRIu32 " servo_error=%" PRIu32
             " elapsed_ms=%" PRIu64 "\n",last_samples,
             r[G2_FEEDBACK/4]&0xffffU,(r[G2_FEEDBACK/4]>>16)&0xffU,now_ms()-start_ms);
      fflush(stdout);
    }
    if (st&DONE) break;
    if (interrupted || now_ms()>host_deadline) {
      r[G2_CMD/4]=0x47320002U;
      fputs("ERR cancelled_or_host_timeout; a sent motion frame cannot be undone\n",stderr);
      goto done;
    }
    pause_ms(5);
  } while (1);
  uint32_t fault=r[G2_FAULT/4];
  unsigned start=r[G2_START/4]&65535U;
  position=r[G2_FEEDBACK/4]&65535U;
  printf("result id=%u start=",id);
  if (st&START_VALID) printf("%u",start); else printf("UNAVAILABLE");
  printf(" target=%u last=",target);
  if (st&FEEDBACK_VALID) printf("%u",position); else printf("UNAVAILABLE");
  if ((st&START_VALID) && (st&FEEDBACK_VALID))
    printf(" actual_delta=%d target_error=%u position_change_observed=%u"
           " in_band=%u",(int)position-(int)start,
           position>target?position-target:target-position,
           (st&POSITION_CHANGED)!=0,
           (position>target?position-target:target-position)<=tolerance);
  printf(" write_sent=%u unicast_ack=%u fault=%" PRIu32 " fault_id=%u\n",
         (st&WRITE_SENT)!=0,(st&WRITE_ACK)!=0,fault,id);
  if (st&ERROR || !(st&WRITE_SENT)) {
    fprintf(stderr,"ERR g2_fault=%" PRIu32 " fault_id=%u write_sent=%u unicast_ack=%u"
                   " position_feedback_valid=%u\n",
      fault,id,(st&WRITE_SENT)!=0,(st&WRITE_ACK)!=0,
      (st&FEEDBACK_VALID)!=0);
    goto done;
  }
  if (!(st&START_VALID) || !(st&FEEDBACK_VALID) || !(st&WRITE_ACK) ||
      (position>target ? position-target : target-position)>tolerance) {
    fprintf(stderr,"ERR incomplete_or_out_of_band_result target=%u position_raw=%u\n",target,position);
    goto done;
  }
  printf("RTCS_PL_G2_OK id=%u target=%u position_raw=%u final_error=%u"
         " actual_delta=%d position_change_observed=%u"
         " samples=%" PRIu32 " elapsed_ms=%" PRIu64 " timing=%s\n",
         id,target,position,position>target?position-target:target-position,
         (int)position-(int)start,(st&POSITION_CHANGED)!=0,
         (st>>8)&0xffU,now_ms()-start_ms,st&LATE?"AFTER_2S":"WITHIN_2S");
  result=EXIT_SUCCESS;
done:
  munmap(mapping,MAP_BYTES); close(fd); return result;
}
