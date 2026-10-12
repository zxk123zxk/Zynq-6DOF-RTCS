#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
build_dir="$repo_root/build/sim"
mkdir -p "$build_dir"
gcc -std=c11 -Wall -Wextra -Werror -O2 \
  "$repo_root/src/ps/linux/apps/rtcs_pl_g2_six.c" -o "$build_dir/rtcs-pl-g2-six-host"
mock="$build_dir/g2-six-abi14.mock-uio"
truncate -s 0 "$mock"
truncate -s 65536 "$mock"
write_u32() {
  python3 - "$mock" "$1" "$2" <<'PY'
import struct, sys
with open(sys.argv[1], 'r+b') as f:
    f.seek(int(sys.argv[2], 0))
    f.write(struct.pack('<I', int(sys.argv[3], 0)))
PY
}
read_u32() { od -An -tu4 -j"$1" -N4 "$mock" | tr -d ' '; }
write_u32 0 0x5254000e
write_u32 92 2
write_u32 96 2000
# inventory 已删除（diagnose 的严格子集）：必须作为未知动词被拒，且一帧不发。
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" inventory \
    >"$build_dir/six-inventory-removed.out" 2>&1; then
  echo 'Removed verb inventory was still accepted' >&2; exit 1
fi
grep -q 'usage:' "$build_dir/six-inventory-removed.out"
[[ $(read_u32 200) == 0 ]]
"$build_dir/rtcs-pl-g2-six-host" --uio "$mock" diagnose >"$build_dir/six-diagnose-ok.out"
grep -q 'RTCS_PL_G2_SIX_DIAG OK issues=0 read_only=1 write_sent=0' "$build_dir/six-diagnose-ok.out"
[[ $(grep -c '^diagnose id=' "$build_dir/six-diagnose-ok.out") == 6 ]]
[[ $(read_u32 200) == 0 ]]
write_u32 92 6
write_u32 100 8
write_u32 96 $((4*65536+2500))
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" diagnose >"$build_dir/six-diagnose-servo-error.out"; then
  echo 'Diagnostic accepted a nonzero servo ERROR byte' >&2; exit 1
fi
grep -q 'diagnose id=5 position_raw=2500 servo_error=0x04 read_fault=8 status=SERVO_ERROR' \
  "$build_dir/six-diagnose-servo-error.out"
grep -q 'RTCS_PL_G2_SIX_DIAG INCOMPLETE issues=6 read_only=1 write_sent=0' \
  "$build_dir/six-diagnose-servo-error.out"
[[ $(read_u32 200) == 0 ]]
write_u32 100 3
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" diagnose >"$build_dir/six-diagnose-read-fault.out"; then
  echo 'Diagnostic accepted an invalid READ response' >&2; exit 1
fi
grep -q 'diagnose id=2 position_raw=UNAVAILABLE servo_error=UNAVAILABLE read_fault=3 status=READ_FAULT' \
  "$build_dir/six-diagnose-read-fault.out"
write_u32 92 2; write_u32 96 2000; write_u32 100 0
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" diagnose --execute >"$build_dir/six-diagnose-execute.out" 2>&1; then
  echo 'Read-only diagnostic accepted --execute' >&2; exit 1
fi
[[ $(read_u32 200) == 0 ]]
args=(--uio "$mock" move-six)
for n in 1 2 3 4 5 6; do args+=(--axis "$n:2000:1500:10"); done
if "$build_dir/rtcs-pl-g2-six-host" "${args[@]}" --execute >"$build_dir/six-uncalibrated.out" 2>&1; then
  echo 'Uncalibrated six-axis command was accepted' >&2; exit 1
fi
grep -q 'ERR six_axis_uncalibrated' "$build_dir/six-uncalibrated.out"
[[ $(read_u32 200) == 0 ]]
write_u32 216 63
write_u32 240 0; write_u32 244 4000; write_u32 248 2000; write_u32 252 1500
write_u32 92 8
"$build_dir/rtcs-pl-g2-six-host" --uio "$mock" limits >"$build_dir/six-limits.out"
grep -q 'RTCS_PL_G2_SIX_LIMITS_OK calibrated_mask=0x3f' "$build_dir/six-limits.out"
grep -q 'limit id=1 min=0 max=4000 reference_count=2000 speed_raw_max=1500' "$build_dir/six-limits.out"
write_u32 92 2
for raw_speed in 0 1501; do
  invalid=(--uio "$mock" move-six)
  for n in 1 2 3 4 5 6; do
    if [[ $n == 4 ]]; then invalid+=(--axis "$n:2000:$raw_speed:10")
    else invalid+=(--axis "$n:2000:500:10"); fi
  done
  if "$build_dir/rtcs-pl-g2-six-host" "${invalid[@]}" --execute \
      >"$build_dir/six-speed-invalid.out" 2>&1; then
    echo 'Six-axis CLI accepted invalid speed' >&2; exit 1
  fi
  grep -q 'ERR axis=4 target_or_speed_outside_pl_limit' "$build_dir/six-speed-invalid.out"
  [[ $(read_u32 200) == 0 ]]
done
for bad in '--tolerance 2:0' '--tolerance 2:101' '--observe-ms 1050'; do
  read -r -a extra <<<"$bad"
  if "$build_dir/rtcs-pl-g2-six-host" "${args[@]}" "${extra[@]}" --execute \
      >"$build_dir/six-bad-observation.out" 2>&1; then
    echo 'Invalid observation policy was accepted' >&2; exit 1
  fi
  [[ $(read_u32 200) == 0 ]]
done
write_u32 192 0x00120012 # DONE | SENT | 18 post-WRITE READ samples
write_u32 264 2000
write_u32 268 0x3f003f00 # six valid/in-band post-WRITE samples, no starts
write_u32 272 0x00000300 # post-WRITE feedback phase
for offset in 168 172 176 180 184 188; do write_u32 "$offset" 2000; done
"$build_dir/rtcs-pl-g2-six-host" "${args[@]}" --execute >"$build_dir/six-move.out"
grep -q 'RTCS_PL_G2_SIX_OK command=move-six' "$build_dir/six-move.out"
grep -q 'unicast_ack=NOT_APPLICABLE_BROADCAST' "$build_dir/six-move.out"
grep -q 'start_valid_mask=0x00 feedback_valid_mask=0x3f position_change_mask=UNAVAILABLE phase=post_write_feedback' "$build_dir/six-move.out"
grep -q 'result id=2 start=UNAVAILABLE target=2000 last=2000 actual_delta=UNAVAILABLE target_error=0' "$build_dir/six-move.out"
[[ $(read_u32 200) == 1194459139 ]]
[[ $(read_u32 260) == 50 ]]
[[ $(read_u32 256) == 30 ]]

# All six post-WRITE samples must be valid and in band; starts are optional.
write_u32 268 0x3f003e00
if "$build_dir/rtcs-pl-g2-six-host" "${args[@]}" --execute >"$build_dir/six-missing-feedback.out" 2>&1; then
  echo 'Six-axis CLI accepted missing feedback' >&2; exit 1
fi
grep -q 'ERR incomplete_result_snapshot' "$build_dir/six-missing-feedback.out"
write_u32 268 0x3e003f00
if "$build_dir/rtcs-pl-g2-six-host" "${args[@]}" --execute >"$build_dir/six-out-of-band.out" 2>&1; then
  echo 'Six-axis CLI accepted an out-of-band axis' >&2; exit 1
fi
grep -q 'ERR incomplete_result_snapshot' "$build_dir/six-out-of-band.out"
write_u32 268 0x3f003f00
write_u32 200 0
"$build_dir/rtcs-pl-g2-six-host" "${args[@]}" --tolerance 2:40 \
  --observe-ms 6000 --execute >"$build_dir/six-custom-policy.out"
grep -q 'axis=2 target=2000 speed_raw=1500 time_raw=10 tolerance=40' \
  "$build_dir/six-custom-policy.out"
[[ $(read_u32 260) == 60 ]]
write_u32 200 0
if "$build_dir/rtcs-pl-g2-six-host" "${args[@]}" >"$build_dir/six-no-execute.out" 2>&1; then
  echo 'Six-axis command without --execute was accepted' >&2; exit 1
fi
[[ $(read_u32 200) == 0 ]]
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" calibrate-step --id 2 --delta 51 --execute \
  >"$build_dir/six-bad-step.out" 2>&1; then
  echo 'Calibration step >50 was accepted' >&2; exit 1
fi
[[ $(read_u32 200) == 0 ]]
write_u32 268 0x3f003f3f # relative calibration still has a required start
write_u32 192 18  # DONE | WRITE_SENT, simulated PL completion
write_u32 212 2000
write_u32 220 196609 # start valid | write ACK | one sample
write_u32 228 268437506 # valid position 2050
write_u32 232 5000000 # 50 ms
write_u32 268 0x02020202
"$build_dir/rtcs-pl-g2-six-host" --uio "$mock" calibrate-step --id 2 --delta 50 --execute \
  >"$build_dir/six-step.out"
grep -q 'calibrate-start id=2 position_raw=2000 target=2050' "$build_dir/six-step.out"
grep -q 'sample=1 id=2 elapsed_ms=50 position_raw=2050 .*target_error=0' "$build_dir/six-step.out"
grep -q 'calibrate-final id=2 position_raw=2050 target=2050 final_error=0 actual_delta=50' "$build_dir/six-step.out"
[[ $(grep -c '^feedback id=' "$build_dir/six-step.out") == 1 ]]
[[ $(read_u32 200) == 1194459140 ]]
[[ $(read_u32 104) == 2 ]]
[[ $(read_u32 108) == 50 ]]
write_u32 192 6   # DONE | ERROR, with stale feedback still in the mock
write_u32 196 773 # fault 5, ID 3
write_u32 220 0
write_u32 268 0
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" calibrate-step --id 3 --delta 50 --execute \
  >"$build_dir/six-fault.out" 2>&1; then
  echo 'Six-axis CLI accepted a PL fault' >&2; exit 1
fi
grep -q 'ERR g2_six_fault=5 fault_id=3' "$build_dir/six-fault.out"
grep -q 'fault=5 fault_id=3 start_valid_mask=' "$build_dir/six-fault.out"
if grep -q '^feedback id=' "$build_dir/six-fault.out"; then
  echo 'Six-axis CLI printed stale feedback on fault' >&2; exit 1
fi
write_u32 192 22 # DONE | ERROR | WRITE_SENT
write_u32 196 1285 # fault 5, ID 5
write_u32 272 0x003c0308 # raw ERROR 0x3c, post-WRITE, engine fault 8
if "$build_dir/rtcs-pl-g2-six-host" "${args[@]}" --execute \
    >"$build_dir/six-servo-error.out" 2>&1; then
  echo 'Six-axis CLI accepted a servo status fault' >&2; exit 1
fi
grep -q 'command_result write_sent=1 unicast_ack=NOT_APPLICABLE_BROADCAST' \
  "$build_dir/six-servo-error.out"
grep -q 'fault=5 fault_id=5 .*phase=post_write_feedback engine_fault=8 servo_error_raw=0x3c' \
  "$build_dir/six-servo-error.out"
grep -q 'ERR g2_six_fault=5 fault_id=5 write_sent=1 .*servo_error_raw=0x3c' \
  "$build_dir/six-servo-error.out"
grep -q 'servo_error_bits=temperature|current|angle|overload' \
  "$build_dir/six-servo-error.out"
write_u32 272 0

# Preserve the original fault, then read only axes without a PL feedback sample.
write_u32 268 0x00000f00 # post-WRITE samples only ID 1..4, no starts
write_u32 272 0x00100308
write_u32 92 2; write_u32 96 2000; write_u32 100 0
if "$build_dir/rtcs-pl-g2-six-host" "${args[@]}" --execute \
    >"$build_dir/six-post-fault-read-only.out" 2>&1; then
  echo 'Post-fault read-only collection hid the original error' >&2; exit 1
fi
grep -q 'post_fault_read_only original_fault=5 fault_id=5 remaining_mask=0x20 write_sent=0' \
  "$build_dir/six-post-fault-read-only.out"
grep -q 'post_fault_axis=6 diagnose id=6 position_raw=2000' \
  "$build_dir/six-post-fault-read-only.out"
[[ $(read_u32 200) == 1194459139 ]] # no second motion frame
write_u32 268 0x3f003f3f

write_u32 192 22 # DONE | ERROR | WRITE_SENT
write_u32 196 521 # fault 9, ID 2
write_u32 212 871
write_u32 220 196609
write_u32 228 268436333 # valid position 877
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" calibrate-step --id 2 --delta 20 --execute \
    >"$build_dir/six-timeout.out" 2>&1; then
  echo 'Calibration timeout was accepted' >&2; exit 1
fi
grep -q 'position_raw=877 .*target_error=14' "$build_dir/six-timeout.out"
grep -q 'final_error=14 actual_delta=6' "$build_dir/six-timeout.out"
grep -q 'reason=three_consecutive_in_band_not_seen_before_observation_deadline' "$build_dir/six-timeout.out"

write_u32 192 22 # DONE | ERROR | WRITE_SENT
write_u32 196 520 # fault 8, ID 2
write_u32 220 65536 # start valid, no WRITE ACK and no samples
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" calibrate-step --id 2 --delta 20 --execute \
    >"$build_dir/six-write-fault.out" 2>&1; then
  echo 'WRITE fault was accepted' >&2; exit 1
fi
grep -q 'write_ack=0' "$build_dir/six-write-fault.out"
grep -q 'reason=write_or_ack_failure' "$build_dir/six-write-fault.out"

write_u32 192 6 # stop fault 5 before holding broadcast
write_u32 196 773 # ID 3, fault 5
write_u32 272 0x00000103 # pre-WRITE READ, low-level fault 3
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" stop --execute \
  >"$build_dir/six-stop-pre-fault.out" 2>&1; then
  echo 'Stop READ fault was accepted' >&2; exit 1
fi
grep -q 'write_sent=0 .*phase=pre_write_read engine_fault=3' "$build_dir/six-stop-pre-fault.out"
if grep -q 'RTCS_PL_G2_SIX_OK' "$build_dir/six-stop-pre-fault.out"; then exit 1; fi
write_u32 192 22 # stop fault 5 after holding broadcast
write_u32 272 0x00000303
if "$build_dir/rtcs-pl-g2-six-host" --uio "$mock" stop --execute \
  >"$build_dir/six-stop-post-fault.out" 2>&1; then
  echo 'Post-WRITE stop READ fault was accepted' >&2; exit 1
fi
grep -q 'write_sent=1 .*phase=post_write_feedback engine_fault=3' "$build_dir/six-stop-post-fault.out"

write_u32 92 2; write_u32 96 1
"$build_dir/rtcs-pl-g2-six-host" --uio "$mock" torque-status --id 3 \
  >"$build_dir/six-torque.out"
grep -q 'RTCS_PL_G2_SIX_TORQUE id=3 register=0x28 value=1' "$build_dir/six-torque.out"
[[ $(read_u32 84) == 11 ]]
echo RTCS_PL_G2_SIX_CLI_GUARD_PASS
