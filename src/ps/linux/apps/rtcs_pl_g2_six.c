/* ABI 11 六轴操作。所有运动均需显式 --execute；广播限位由 PL 判定。 */
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

enum { MAP_SIZE=65536, ABI=0x5254000c, ID=0, TICKS_LO=0x14, TICKS_HI=0x18,
  TARGET0=0x20, G1_ID=0x50, G1_OP=0x54, G1_CMD=0x58, G1_STATUS=0x5c,
  G1_RESULT=0x60, G1_FAULT=0x64, G2_ID=0x68, G2_DELTA=0x6c,
  PARAM0=0x90, FEEDBACK0=0xa8, STATUS=0xc0, FAULT=0xc4,
  CMD=0xc8, DEADLINE_LO=0xcc, DEADLINE_HI=0xd0,
  CAL_START=0xd4, CAL_MASK=0xd8, LOG_COUNT=0xdc, LOG_INDEX=0xe0,
  LOG_DATA=0xe4, LOG_ELAPSED=0xe8, LIMIT_ID=0xec, LIMIT_MIN=0xf0,
  LIMIT_MAX=0xf4, LIMIT_REFERENCE=0xf8, LIMIT_SPEED_MAX=0xfc,
  TOLERANCE=0x100, OBSERVE=0x104, START_POSITION=0x108,
  RESULT=0x10c, DIAG=0x110,
  BUSY=1, DONE=2, ERROR=4, INHIBITED=8, SENT=16 };
static volatile sig_atomic_t interrupted;
static void on_signal(int sig) { (void)sig; interrupted=1; }
static uint64_t milliseconds(void) {
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC,&t)) return 0;
  return (uint64_t)t.tv_sec*1000U+(uint64_t)t.tv_nsec/1000000U;
}
static void pause_ms(unsigned n) {
  struct timespec t={n/1000U,(long)(n%1000U)*1000000L};
  while (nanosleep(&t,&t) && errno==EINTR && !interrupted) {}
}
static int parse_u16(const char *s,unsigned *out) {
  char *end; unsigned long v;
  if (!s || !*s || *s=='-' || *s=='+') return -1;
  errno=0; v=strtoul(s,&end,10);
  if (errno || *end || v>UINT16_MAX) return -1;
  *out=(unsigned)v; return 0;
}
static int parse_step(const char *s,int *out) {
  char *end; long v;
  if (!s || !*s) return -1;
  errno=0; v=strtol(s,&end,10);
  if (errno || *end || v==0 || v< -50 || v>50) return -1;
  *out=(int)v; return 0;
}
static uint64_t ticks(volatile uint32_t *r) {
  uint32_t hi,lo,hi2;
  do { hi=r[TICKS_HI/4]; lo=r[TICKS_LO/4]; hi2=r[TICKS_HI/4]; } while (hi!=hi2);
  return ((uint64_t)hi<<32)|lo;
}
static void set_deadline(volatile uint32_t *r) {
  uint64_t end=ticks(r)+200000000ULL;
  r[DEADLINE_LO/4]=(uint32_t)end;
  r[DEADLINE_HI/4]=(uint32_t)(end>>32);
}
static int read_register(volatile uint32_t *r,unsigned id,unsigned op,
                         unsigned *value_out) {
  uint64_t end;
  if (r[G1_STATUS/4]&BUSY) {
    fprintf(stderr,"ERR READ id=%u op=%u bus_busy\n",id,op);
    return -1;
  }
  r[G1_CMD/4]=2; __sync_synchronize();
  r[G1_ID/4]=id; r[G1_OP/4]=op; __sync_synchronize();
  r[G1_CMD/4]=1;
  end=milliseconds()+300;
  do {
    uint32_t st=r[G1_STATUS/4];
    if (st&DONE) {
      uint32_t value=r[G1_RESULT/4];
      if (st&ERROR || ((value>>16)&255U)) {
        fprintf(stderr,"ERR READ id=%u op=%u fault=%" PRIu32 " servo_error=%u\n",
          id,op,r[G1_FAULT/4],(value>>16)&255U);
        return -1;
      }
      *value_out=value&65535U; return 0;
    }
    if (st&INHIBITED || interrupted) break;
    pause_ms(1);
  } while (milliseconds()<end);
  r[G1_CMD/4]=2;
  fprintf(stderr,"ERR READ id=%u op=%u timeout_or_inhibit\n",id,op);
  return -1;
}
static const char *fault_reason(unsigned code) {
  switch (code) {
    case 1: return "physical_tx_disabled";
    case 2: return "bus_busy";
    case 3: return "invalid_descriptor_or_step";
    case 4: return "command_deadline_expired";
    case 5: return "read_or_protocol_failure";
    case 8: return "write_or_ack_failure";
    case 9: return "three_consecutive_in_band_not_seen_before_observation_deadline";
    case 11: return "six_axis_uncalibrated";
    case 12: return "measured_limit_rejected";
    case 16: return "in_band_without_observed_position_change";
    case 17: return "tolerance_outside_1_100";
    case 18: return "observation_outside_1000_10000ms";
    case 14: return "calibration_log_overflow";
    case 15: return "speed_raw_outside_1_1500";
    default: return "unknown";
  }
}
static void print_calibration_log(volatile uint32_t *r,unsigned id,int delta,
                                  uint32_t st) {
  uint32_t meta=r[LOG_COUNT/4], count=meta&255U;
  unsigned start=r[CAL_START/4],target=0,final=0,have_final=0;
  if (meta&(1U<<16)) {
    target=(unsigned)((int)start+delta);
    printf("calibrate-start id=%u position_raw=%u target=%u requested_delta=%d"
           " write_sent=%u write_ack=%u\n",
           id,start,target,delta,(st&SENT)!=0,(meta>>17)&1U);
  } else printf("calibrate-start id=%u position_raw=UNAVAILABLE target=UNAVAILABLE"
                " write_sent=%u write_ack=%u\n",
                id,(st&SENT)!=0,(meta>>17)&1U);
  for (unsigned n=0;n<count;n++) {
    r[LOG_INDEX/4]=n; __sync_synchronize();
    uint32_t data=r[LOG_DATA/4],elapsed=r[LOG_ELAPSED/4];
    unsigned valid=(data>>28)&1U,position=data&65535U;
    if (valid) { final=position; have_final=1; }
    printf("sample=%u id=%u elapsed_ms=%" PRIu32 " position_raw=",
           n+1,id,elapsed/100000U);
    if (valid) printf("%u",position); else printf("UNAVAILABLE");
    printf(" servo_error=%u read_fault=%u",(data>>16)&255U,(data>>24)&15U);
    if (valid && (meta&(1U<<16)))
      printf(" target_error=%u",position>target?position-target:target-position);
    putchar('\n');
  }
  if (have_final && (meta&(1U<<16)))
    printf("calibrate-final id=%u position_raw=%u target=%u final_error=%u"
           " actual_delta=%d samples=%u\n",id,final,target,
           final>target?final-target:target-final,(int)final-(int)start,count);
  else printf("calibrate-final id=%u position_raw=UNAVAILABLE final_error=UNAVAILABLE"
              " samples=%u\n",id,count);
  fflush(stdout);
}
static int parse_axis(const char *value,unsigned *id,unsigned *target,
                      unsigned *speed,unsigned *time_raw) {
  char text[96],*parts[4],*next;
  if (strlen(value)>=sizeof(text)) return -1;
  strcpy(text,value); next=text;
  for (int i=0;i<4;i++) {
    parts[i]=next;
    if (i<3) {
      next=strchr(next,':');
      if (!next) return -1;
      *next++=0;
    } else if (strchr(next,':')) return -1;
  }
  return parse_u16(parts[0],id) || parse_u16(parts[1],target) ||
         parse_u16(parts[2],speed) || parse_u16(parts[3],time_raw) ? -1:0;
}
static int read_limit(volatile uint32_t *r,unsigned id,unsigned *lo,
                      unsigned *hi,unsigned *reference,unsigned *speed_max) {
  if (id<1 || id>6 || !(r[CAL_MASK/4]&(1U<<(id-1)))) return -1;
  r[LIMIT_ID/4]=id; __sync_synchronize();
  if (r[LIMIT_ID/4]!=id) return -1;
  *lo=r[LIMIT_MIN/4]; *hi=r[LIMIT_MAX/4];
  *reference=r[LIMIT_REFERENCE/4]; *speed_max=r[LIMIT_SPEED_MAX/4];
  return *lo<=*reference && *reference<=*hi && *hi<=UINT16_MAX &&
         *speed_max==1500 ? 0:-1;
}
static int parse_tolerance_axis(const char *s,unsigned *id,unsigned *tol) {
  char copy[32],*colon;
  if (strlen(s)>=sizeof(copy)) return -1;
  strcpy(copy,s); colon=strchr(copy,':');
  if (!colon || strchr(colon+1,':')) return -1;
  *colon++=0;
  return parse_u16(copy,id) || parse_u16(colon,tol) ||
         *id<1 || *id>6 || *tol<1 || *tol>100 ? -1:0;
}
static const char *phase_name(unsigned phase) {
  switch (phase) {
    case 1: return "pre_write_read";
    case 2: return "write_or_ack";
    case 3: return "post_write_feedback";
    default: return "pre_commit";
  }
}
static void print_motion_result(volatile uint32_t *r,const char *verb,
                                const unsigned goals[6],unsigned cal_id) {
  uint32_t flags=r[RESULT/4];
  for (unsigned id=1;id<=6;id++) {
    if (!strcmp(verb,"calibrate-step") && id!=cal_id) continue;
    unsigned bit=1U<<(id-1),start=0,last=0,target=goals[id-1];
    r[LIMIT_ID/4]=id; __sync_synchronize();
    if (flags&bit) start=r[START_POSITION/4]&65535U;
    if (!strcmp(verb,"stop") && (flags&bit)) target=start;
    if (flags&(bit<<8)) last=r[(FEEDBACK0+4*(id-1))/4]&65535U;
    printf("result id=%u start=",id);
    if (flags&bit) printf("%u",start); else printf("UNAVAILABLE");
    printf(" target=");
    if (!(flags&bit) && (!strcmp(verb,"stop") ||
                         !strcmp(verb,"calibrate-step")))
      printf("UNAVAILABLE");
    else printf("%u",target);
    printf(" last=");
    if (flags&(bit<<8)) printf("%u",last); else printf("UNAVAILABLE");
    if ((flags&bit) && (flags&(bit<<8)))
      printf(" actual_delta=%d target_error=%u position_change_observed=%u"
             " in_band=%u",(int)last-(int)start,
             last>target?last-target:target-last,
             (flags&(bit<<16))!=0,(flags&(bit<<24))!=0);
    else printf(" actual_delta=UNAVAILABLE target_error=UNAVAILABLE");
    putchar('\n');
  }
  fflush(stdout);
}
static void usage(const char *name) {
  fprintf(stderr,"usage: %s --uio /dev/uioN inventory\n"
    "       %s --uio /dev/uioN limits\n"
    "       %s --uio /dev/uioN calibrate-step --id 2..6 --delta -50..50"
    " [--tolerance 1..100] [--observe-ms 1000..10000] --execute\n"
    "       %s --uio /dev/uioN torque-status --id 1..6\n"
    "       %s --uio /dev/uioN move-six --axis ID:target:speed-raw:time-raw"
    " (repeat six times) [--tolerance ID:1..100]..."
    " [--observe-ms 1000..10000] --execute\n"
    "       %s --uio /dev/uioN stop --execute\n",name,name,name,name,name,name);
}
int main(int argc,char **argv) {
  const char *path=NULL,*verb=NULL;
  unsigned id=0,seen_id=0,seen_delta=0,execute=0,axis_mask=0,tol_mask=0;
  unsigned goal[6]={0},speed[6]={0},time_raw[6]={0};
  unsigned tol[6]={30,30,30,30,30,30},cal_tol=5,observe_ms=5000;
  unsigned seen_observe=0,seen_cal_tol=0;
  int delta=0,fd=-1,rc=EXIT_FAILURE,requested_stop=0;
  volatile uint32_t *r; void *map;
  uint64_t end,start;
  for (int i=1;i<argc;i++) {
    if (!strcmp(argv[i],"--uio") && i+1<argc) path=argv[++i];
    else if (!strcmp(argv[i],"--id") && i+1<argc)
      seen_id++, seen_id+=(parse_u16(argv[++i],&id)!=0);
    else if (!strcmp(argv[i],"--delta") && i+1<argc)
      seen_delta++, seen_delta+=(parse_step(argv[++i],&delta)!=0);
    else if (!strcmp(argv[i],"--observe-ms") && i+1<argc)
      seen_observe++, seen_observe+=(parse_u16(argv[++i],&observe_ms)!=0);
    else if (!strcmp(argv[i],"--tolerance") && i+1<argc) {
      const char *value=argv[++i];
      if (strchr(value,':')) {
        unsigned n,t;
        if (parse_tolerance_axis(value,&n,&t) || (tol_mask&(1U<<(n-1)))) {
          usage(argv[0]); return rc;
        }
        tol_mask|=1U<<(n-1); tol[n-1]=t;
      } else {
        seen_cal_tol++, seen_cal_tol+=(parse_u16(value,&cal_tol)!=0);
      }
    }
    else if (!strcmp(argv[i],"--axis") && i+1<argc) {
      unsigned n,t,s,tm;
      if (parse_axis(argv[++i],&n,&t,&s,&tm) || n<1 || n>6 ||
          (axis_mask&(1U<<(n-1)))) { usage(argv[0]); return rc; }
      axis_mask|=1U<<(n-1); goal[n-1]=t; speed[n-1]=s; time_raw[n-1]=tm;
    } else if (!strcmp(argv[i],"--execute")) execute++;
    else if (!verb && (!strcmp(argv[i],"inventory") || !strcmp(argv[i],"limits") ||
                      !strcmp(argv[i],"calibrate-step") ||
                      !strcmp(argv[i],"torque-status") ||
                      !strcmp(argv[i],"move-six") || !strcmp(argv[i],"stop"))) verb=argv[i];
    else { usage(argv[0]); return rc; }
  }
  if (!path || !verb || execute>1 || seen_observe>1 || seen_cal_tol>1 ||
      observe_ms<1000 || observe_ms>10000 || observe_ms%100 ||
      cal_tol<1 || cal_tol>100 ||
      (!strcmp(verb,"inventory") && (execute || seen_id || seen_delta || axis_mask ||
         tol_mask || seen_cal_tol || seen_observe)) ||
      (!strcmp(verb,"limits") && (execute || seen_id || seen_delta || axis_mask ||
         tol_mask || seen_cal_tol || seen_observe)) ||
      (!strcmp(verb,"calibrate-step") && (execute!=1 || seen_id!=1 ||
         seen_delta!=1 || id<2 || id>6 || axis_mask || tol_mask)) ||
      (!strcmp(verb,"torque-status") && (execute || seen_id!=1 ||
         id<1 || id>6 || seen_delta || axis_mask || tol_mask ||
         seen_cal_tol || seen_observe)) ||
      (!strcmp(verb,"move-six") && (execute!=1 || seen_id || seen_delta ||
         axis_mask!=63U || seen_cal_tol)) ||
      (!strcmp(verb,"stop") && (execute!=1 || seen_id || seen_delta || axis_mask ||
         tol_mask || seen_cal_tol || seen_observe))) {
    usage(argv[0]); return rc;
  }
  fd=open(path,O_RDWR|O_SYNC);
  if (fd<0) { perror("ERR open_uio"); return rc; }
  if (flock(fd,LOCK_EX|LOCK_NB)) { perror("ERR bus_locked"); close(fd); return rc; }
  map=mmap(NULL,MAP_SIZE,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
  if (map==MAP_FAILED) { perror("ERR mmap_uio"); close(fd); return rc; }
  r=(volatile uint32_t *)map;
  if (r[ID/4]!=ABI) {
    fprintf(stderr,"ERR incompatible_pl_id=0x%08" PRIx32 " expected=0x%08x\n",r[ID/4],ABI);
    goto out;
  }
  printf("RTCS_PL_G2_SIX abi=0x%08x physical_tx=%s calibrated_mask=0x%02" PRIx32
         "\n",ABI,r[G1_STATUS/4]&INHIBITED?"DISABLED":"ENABLED",
         r[CAL_MASK/4]&63U);
  if (!strcmp(verb,"limits")) {
    for (unsigned n=1;n<=6;n++) {
      unsigned lo,hi,reference,speed_max;
      if (read_limit(r,n,&lo,&hi,&reference,&speed_max)) {
        fprintf(stderr,"ERR missing_or_invalid_pl_limit id=%u\n",n); goto out;
      }
      printf("limit id=%u min=%u max=%u reference_count=%u speed_raw_max=%u\n",
             n,lo,hi,reference,speed_max);
    }
    puts("RTCS_PL_G2_SIX_LIMITS_OK calibrated_mask=0x3f");
    rc=EXIT_SUCCESS; goto out;
  }
  if (r[G1_STATUS/4]&INHIBITED) { fputs("ERR physical_tx_disabled\n",stderr); goto out; }
  signal(SIGINT,on_signal); signal(SIGTERM,on_signal);
  if (!strcmp(verb,"inventory")) {
    if (r[G1_STATUS/4]&BUSY) { fputs("ERR bus_busy\n",stderr); goto out; }
    for (unsigned n=1;n<=6;n++) {
      unsigned position;
      if (read_register(r,n,2,&position)) goto out;
      printf("id=%u position_raw=%u\n",n,position);
    }
    puts("RTCS_PL_G2_SIX_INVENTORY_OK ids=1,2,3,4,5,6");
    rc=EXIT_SUCCESS; goto out;
  }
  if (!strcmp(verb,"torque-status")) {
    unsigned torque;
    if (read_register(r,id,11,&torque)) goto out;
    printf("RTCS_PL_G2_SIX_TORQUE id=%u register=0x28 value=%u\n",id,torque&255U);
    rc=EXIT_SUCCESS; goto out;
  }
  if (r[STATUS/4]&BUSY && strcmp(verb,"stop")) {
    fputs("ERR g2_busy\n",stderr); goto out;
  }
  if (!strcmp(verb,"move-six") && (r[CAL_MASK/4]&63U)!=63U) {
    fputs("ERR six_axis_uncalibrated; measured limits must be compiled into PL\n",stderr);
    goto out;
  }
  if (!strcmp(verb,"move-six")) {
    for (unsigned n=1;n<=6;n++) {
      unsigned lo,hi,reference,speed_max;
      if (read_limit(r,n,&lo,&hi,&reference,&speed_max)) {
        fprintf(stderr,"ERR missing_or_invalid_pl_limit id=%u\n",n); goto out;
      }
      if (goal[n-1]<lo || goal[n-1]>hi || speed[n-1]==0 ||
          speed[n-1]>speed_max) {
        fprintf(stderr,"ERR axis=%u target_or_speed_outside_pl_limit"
                       " target=%u speed_raw=%u range=%u..%u speed_max=%u\n",
                n,goal[n-1],speed[n-1],lo,hi,speed_max);
        goto out;
      }
    }
  }
  if (!strcmp(verb,"calibrate-step")) {
    unsigned lo,hi,reference,speed_max;
    if (read_limit(r,id,&lo,&hi,&reference,&speed_max) || speed_max<500) {
      fprintf(stderr,"ERR missing_or_invalid_pl_limit id=%u\n",id); goto out;
    }
    r[G2_ID/4]=id;
    r[G2_DELTA/4]=(uint32_t)delta;
    tol[id-1]=cal_tol;
    printf("calibrate-step id=%u delta=%d speed_raw=500 time_raw=10"
           " tolerance=%u observe_ms=%u\n",id,delta,cal_tol,observe_ms);
  } else if (!strcmp(verb,"move-six")) {
    for (unsigned n=0;n<6;n++) {
      r[(TARGET0+4*n)/4]=goal[n];
      r[(PARAM0+4*n)/4]=(time_raw[n]<<16)|speed[n];
      printf("axis=%u target=%u speed_raw=%u time_raw=%u tolerance=%u"
             " torque=0x28:1\n",n+1,goal[n],speed[n],time_raw[n],tol[n]);
    }
  } else puts("stop_requested=READ_six_then_SYNC_hold; completion_not_yet_confirmed");
  if (strcmp(verb,"stop")) {
    for (unsigned n=1;n<=6;n++) {
      r[LIMIT_ID/4]=n; __sync_synchronize();
      r[TOLERANCE/4]=tol[n-1];
    }
    r[OBSERVE/4]=observe_ms/100;
  }
  set_deadline(r); __sync_synchronize();
  start=milliseconds();
  r[CMD/4]=!strcmp(verb,"calibrate-step")?0x47320004U:
           !strcmp(verb,"move-six")?0x47320003U:0x47320005U;
  pause_ms(1); /* 避免读取到上一条命令的 DONE 状态。 */
  end=start+13000;
  for (;;) {
    uint32_t st=r[STATUS/4];
    if (st&DONE) {
      uint32_t fault=r[FAULT/4];
      if (!strcmp(verb,"calibrate-step")) {
        print_calibration_log(r,id,delta,st);
        if (r[LOG_COUNT/4]&(1U<<16))
          goal[id-1]=(unsigned)((int)r[CAL_START/4]+delta);
      }
      print_motion_result(r,verb,goal,id);
      uint32_t flags=r[RESULT/4],diag=r[DIAG/4];
      unsigned expected=!strcmp(verb,"calibrate-step") ? (1U<<(id-1)) : 63U;
      printf("command_result write_sent=%u unicast_ack=",(st&SENT)!=0);
      if (!strcmp(verb,"calibrate-step"))
        printf("%u",(r[LOG_COUNT/4]>>17)&1U);
      else printf("NOT_APPLICABLE_BROADCAST");
      printf(" fault=%u fault_id=%u start_valid_mask=0x%02x feedback_valid_mask=0x%02x"
             " position_change_mask=0x%02x phase=%s engine_fault=%u\n",
             fault&255U,(fault>>8)&255U,
             flags&63U,(flags>>8)&63U,(flags>>16)&63U,
             phase_name((diag>>8)&255U),diag&15U);
      if (st&ERROR || !(st&SENT)) {
        fprintf(stderr,"ERR g2_six_fault=%u fault_id=%u write_sent=%u"
                       " reason=%s phase=%s engine_fault=%u\n",
          fault&255U,(fault>>8)&255U,(st&SENT)!=0,
          fault_reason(fault&255U),phase_name((diag>>8)&255U),diag&15U);
      } else {
        if ((flags&expected)!=expected || ((flags>>8)&expected)!=expected) {
          fputs("ERR incomplete_result_snapshot\n",stderr); break;
        }
        for (unsigned n=0;n<6;n++) {
          if (!strcmp(verb,"calibrate-step") && n+1!=id) continue;
          uint32_t sample=r[(FEEDBACK0+4*n)/4];
          printf("feedback id=%u position_raw=%u servo_error=%u\n",
            n+1,sample&65535U,(sample>>16)&255U);
        }
        if (requested_stop)
          printf("RTCS_PL_G2_SIX_STOPPED after_interrupt elapsed_ms=%" PRIu64 "\n",
            milliseconds()-start);
        else {
          printf("RTCS_PL_G2_SIX_OK command=%s elapsed_ms=%" PRIu64 "\n",
            verb,milliseconds()-start);
          rc=EXIT_SUCCESS;
        }
      }
      break;
    }
    if (interrupted && !requested_stop) {
      requested_stop=1; set_deadline(r); __sync_synchronize();
      r[CMD/4]=0x47320005U;
      fputs("ERR interrupted; software_stop_requested\n",stderr);
      end=milliseconds()+13000;
    }
    if (milliseconds()>end) {
      fputs("ERR host_wait_timeout; WRITE may already have been sent\n",stderr);
      break;
    }
    pause_ms(5);
  }
  if (requested_stop) rc=EXIT_FAILURE;
out:
  munmap(map,MAP_SIZE); close(fd); return rc;
}
