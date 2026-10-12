#ifndef RTCS_SERVO_DIAG_H
#define RTCS_SERVO_DIAG_H

/* HX-30HM register table, 0x41: bit 0..5 = voltage, sensor,
 * temperature, current, angle, overload. Bits 6..7 are undocumented. */
static void print_servo_error_bits(FILE *out, unsigned error) {
  static const char *const names[6] = {
    "voltage", "sensor", "temperature", "current", "angle", "overload"
  };
  if (error == 0) { fputs("none",out); return; }
  int first=1;
  for (unsigned bit=0; bit<6; bit++) if (error & (1U<<bit)) {
    fprintf(out,"%s%s",first?"":"|",names[bit]); first=0;
  }
  if (error & 0xc0U) fprintf(out,"%sreserved_6_7_0x%02x",first?"":"|",error&0xc0U);
}
static uint64_t epoch_ms(void) {
  struct timespec t;
  if (clock_gettime(CLOCK_REALTIME,&t)) return 0;
  return (uint64_t)t.tv_sec*1000U+(uint64_t)t.tv_nsec/1000000U;
}

/* 引擎故障码：hx30hm_g1_engine.sv 的 fault_code，出现在 G1_FAULT 低四位，
 * 也出现在 G2_DIAG 的 [3:0]。写应答阶段这些码曾会被 rtcs_top 压成 G2
 * fault=8 后丢失，必须先把“哪一类”看清楚再谈排查方向。 */
static const char *engine_fault_name(unsigned code)
{
  switch (code) {
    case 0: return "none";
    case 1: return "invalid_servo_id";
    case 2: return "unsupported_opcode";
    case 3: return "response_timeout_no_reply";
    case 4: return "response_length_mismatch";
    case 5: return "response_framing_error";
    case 6: return "response_id_mismatch";
    case 7: return "response_checksum_mismatch";
    case 8: return "servo_returned_nonzero_error";
    default: return "unknown";
  }
}

/* 3..7 = 压根没拿到一条可信应答（传输层）；8 = 拿到了校验有效的应答，
 * 但舵机自报 ERROR 非零（舵机层）。两者排查方向完全相反。 */
static const char *engine_fault_class(unsigned code)
{
  switch (code) {
    case 3: case 4: case 5: case 6: case 7: return "transport";
    case 8: return "servo_error";
    default: return "n/a";
  }
}
#endif
