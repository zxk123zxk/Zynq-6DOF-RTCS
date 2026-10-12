#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
build_dir="$repo_root/build/sim"
mkdir -p "$build_dir"
gcc -std=c11 -Wall -Wextra -Werror -O2 \
  "$repo_root/src/ps/linux/apps/rtcs_pl_g2.c" -o "$build_dir/rtcs-pl-g2-host"
mock="$build_dir/g2-abi12.mock-uio"
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
write_u32 92 8
"$build_dir/rtcs-pl-g2-host" --uio "$mock" probe |
  grep -q 'abi=0x5254000e physical_tx=DISABLED'
args=(--uio "$mock" move --id 1 --target 2100 --speed-raw 500 --time-raw 22136)

if "$build_dir/rtcs-pl-g2-host" "${args[@]}" >"$build_dir/g2-no-execute.out" 2>&1; then
  echo 'G2 accepted a move without --execute' >&2; exit 1
fi
[[ $(read_u32 128) == 0 ]]
if "$build_dir/rtcs-pl-g2-host" "${args[@]}" --execute >"$build_dir/g2-inhibited.out" 2>&1; then
  echo 'G2 accepted an inhibited move' >&2; exit 1
fi
grep -q 'ERR busy_or_inhibited' "$build_dir/g2-inhibited.out"
[[ $(read_u32 128) == 0 ]]

write_u32 92 0
write_u32 216 63  # all six installed limits are compiled
write_u32 240 0; write_u32 244 4000; write_u32 248 2000; write_u32 252 1500
write_u32 108 0xdeadbeef # replaced by tolerance/observation descriptor on commit
for invalid in \
  '--id 7 --target 2100 --speed-raw 500 --time-raw 22136' \
  '--id 1 --target 65536 --speed-raw 500 --time-raw 22136' \
  '--id 1 --target 2100 --speed-raw 65536 --time-raw 22136' \
  '--id 1 --target 2100 --speed-raw 500 --time-raw 65536'; do
  # Intentional word splitting of fixed test vectors.
  read -r -a opts <<<"$invalid"
  if "$build_dir/rtcs-pl-g2-host" --uio "$mock" move "${opts[@]}" --execute \
      >"$build_dir/g2-invalid.out" 2>&1; then
    echo 'G2 accepted an invalid descriptor' >&2; exit 1
  fi
  [[ $(read_u32 128) == 0 ]]
done
for bad in '--tolerance 0' '--tolerance 101' '--observe-ms 1050' '--observe-ms 10001'; do
  read -r -a extra <<<"$bad"
  if "$build_dir/rtcs-pl-g2-host" "${args[@]}" "${extra[@]}" --execute \
      >"$build_dir/g2-bad-policy.out" 2>&1; then
    echo 'Single-axis CLI accepted invalid observation policy' >&2; exit 1
  fi
  [[ $(read_u32 128) == 0 ]]
done

for invalid in \
  '--id 1 --target 2100 --speed-raw 0 --time-raw 10' \
  '--id 1 --target 2100 --speed-raw 1501 --time-raw 10' \
  '--id 1 --target 4001 --speed-raw 500 --time-raw 10'; do
  read -r -a opts <<<"$invalid"
  if "$build_dir/rtcs-pl-g2-host" --uio "$mock" move "${opts[@]}" --execute \
      >"$build_dir/g2-measured-limit.out" 2>&1; then
    echo 'Single-axis CLI accepted target/speed outside PL limits' >&2; exit 1
  fi
  grep -q 'ERR target_or_speed_outside_pl_limit' "$build_dir/g2-measured-limit.out"
  [[ $(read_u32 128) == 0 ]]
done

write_u32 132 0x10392 # DONE | SENT | feedback valid | ACK | three samples
write_u32 140 2100
write_u32 276 2000
"$build_dir/rtcs-pl-g2-host" "${args[@]}" --execute >"$build_dir/g2-move.out"
grep -q 'commit id=1 target=2100 speed_raw=500 time_raw=22136 tolerance=30 observe_ms=5000 torque_toggle=0x28:1' \
  "$build_dir/g2-move.out"
grep -q 'RTCS_PL_G2_OK id=1 target=2100 position_raw=2100' "$build_dir/g2-move.out"
grep -q 'result id=1 start=UNAVAILABLE target=2100 last=2100' "$build_dir/g2-move.out"
[[ $(read_u32 108) == $((0x0032001e)) ]] # 5 s, tolerance 30
[[ $(read_u32 112) == 2100 ]]
[[ $(read_u32 116) == $((0x56780000+500)) ]]
[[ $(read_u32 128) == 1194459137 ]]

# DONE without a normal unicast ACK or valid post-WRITE position is never OK.
write_u32 132 0x92
if "$build_dir/rtcs-pl-g2-host" "${args[@]}" --execute >"$build_dir/g2-no-ack.out" 2>&1; then
  echo 'Single-axis CLI accepted missing WRITE ACK' >&2; exit 1
fi
grep -q 'ERR incomplete_or_out_of_band_result' "$build_dir/g2-no-ack.out"
write_u32 132 0x10012
if "$build_dir/rtcs-pl-g2-host" "${args[@]}" --execute >"$build_dir/g2-no-feedback.out" 2>&1; then
  echo 'Single-axis CLI accepted missing post-WRITE feedback' >&2; exit 1
fi
grep -q 'last=UNAVAILABLE' "$build_dir/g2-no-feedback.out"
write_u32 132 0x10392

# A second independent command can submit a different target without PL reset.
write_u32 128 0
write_u32 140 1998
"$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 1 --target 1998 \
  --speed-raw 50 --time-raw 0 --execute >"$build_dir/g2-second.out"
grep -q 'RTCS_PL_G2_OK id=1 target=1998' "$build_dir/g2-second.out"
[[ $(read_u32 112) == 1998 ]]
[[ $(read_u32 116) == 50 ]]

for axis in 2 3 4 5 6; do
  write_u32 128 0
  write_u32 140 2000
  "$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id "$axis" --target 2000 \
    --speed-raw 1500 --time-raw 10 --execute >"$build_dir/g2-axis-$axis.out"
  grep -q "RTCS_PL_G2_OK id=$axis target=2000" "$build_dir/g2-axis-$axis.out"
  [[ $(read_u32 104) == $axis ]]
done

# Delay after the 2 s write deadline is informational if feedback meets ±15.
write_u32 128 0
write_u32 132 0x103b2 # DONE | SENT | LATE | feedback valid | ACK | three samples
write_u32 140 2001
"$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 1 --target 1998 \
  --speed-raw 50 --time-raw 0 --execute >"$build_dir/g2-late.out"
grep -q 'final_error=3 .*timing=AFTER_2S' "$build_dir/g2-late.out"
write_u32 128 0
write_u32 140 2014
if "$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 1 --target 1998 \
    --speed-raw 50 --time-raw 0 --tolerance 15 --execute >"$build_dir/g2-error.out" 2>&1; then
  echo 'G2 accepted final position beyond configured 15 counts' >&2; exit 1
fi
grep -q 'ERR incomplete_or_out_of_band_result' "$build_dir/g2-error.out"

write_u32 132 0x10096 # current command fault, WRITE ACK and feedback valid
write_u32 136 9
write_u32 276 871
write_u32 140 880
if "$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 2 --target 891 \
    --speed-raw 500 --time-raw 10 --tolerance 5 --execute \
    >"$build_dir/g2-partial.out" 2>&1; then
  echo 'Partial movement outside tolerance was accepted' >&2; exit 1
fi
grep -q 'actual_delta=UNAVAILABLE position_change_observed=UNAVAILABLE target_error=11 in_band=0' "$build_dir/g2-partial.out"
grep -q 'ERR g2_fault=9 fault_id=2 write_sent=1 unicast_ack=1 position_feedback_valid=1' "$build_dir/g2-partial.out"
grep -q 'write_sent=1 unicast_ack=1 fault=9 fault_id=2' "$build_dir/g2-partial.out"
write_u32 132 0x10392 # valid stable feedback; no start or change requirement
write_u32 136 0
write_u32 276 2080
write_u32 140 2080
"$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 1 --target 2100 \
    --speed-raw 500 --time-raw 10 --execute >"$build_dir/g2-static.out"
grep -q 'actual_delta=UNAVAILABLE position_change_observed=UNAVAILABLE target_error=20 in_band=1' "$build_dir/g2-static.out"
grep -q 'RTCS_PL_G2_OK id=1' "$build_dir/g2-static.out"

# A checksum-valid WRITE reply with ERROR=0x10 has no unicast ACK and
# no position sample. Its position field must not be treated as a READ.
write_u32 132 0x16 # DONE | ERROR | SENT; no pre-WRITE READ
write_u32 136 8
write_u32 100 8
write_u32 96 0x00100000
write_u32 276 2013
if "$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 5 --target 3000 \
  --speed-raw 500 --time-raw 10 --execute >"$build_dir/g2-angle-error.out" 2>&1; then
  echo 'Single-axis CLI accepted ERROR=0x10' >&2; exit 1
fi
grep -q 'diagnostic phase=write_ack engine_fault=8 servo_error_raw=0x10 servo_error_bits=angle incident_position=UNAVAILABLE incident_position_valid=0' \
  "$build_dir/g2-angle-error.out"
grep -q 'last=UNAVAILABLE .*write_sent=1 unicast_ack=0' "$build_dir/g2-angle-error.out"
grep -q 'diag_latched=0' "$build_dir/g2-angle-error.out"
write_u32 100 0

# 当 PL 提供 G2_DIAG 锁存时，CLI 必须优先采用它，而不是可被后续总线事务
# 覆盖的当刻 G1_FAULT/G1_RESULT。这里故意让 G1_FAULT 撒谎为“应答超时”。
write_u32 132 0x16       # DONE | ERROR | SENT
write_u32 136 8          # G2 fault 8
write_u32 100 3          # G1_FAULT 会声称是应答超时
write_u32 280 0x00100258 # G2_DIAG: servo 0x10, phase 2, axis 5, engine 8
if "$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 5 --target 3000 \
  --speed-raw 500 --time-raw 10 --execute >"$build_dir/g2-diag-latched.out" 2>&1; then
  echo 'Single-axis CLI accepted a latched servo-error snapshot' >&2; exit 1
fi
grep -q 'diag_latched=1' "$build_dir/g2-diag-latched.out"
grep -q 'engine_fault=8' "$build_dir/g2-diag-latched.out"
grep -q 'engine_class=servo_error engine_reason=servo_returned_nonzero_error fault_axis=5' \
  "$build_dir/g2-diag-latched.out"
grep -q 'servo_error_raw=0x10' "$build_dir/g2-diag-latched.out"
[[ $(read_u32 280) == $((0x00100258)) ]]
write_u32 280 0
write_u32 100 0

# 提交前的读阶段被舵机 ERROR 拦下：write_sent=0，绝不能写成“运动帧已被接受”。
write_u32 132 0x06       # DONE | ERROR，本次没有发出运动帧
write_u32 136 5          # G2 fault 5
write_u32 100 8          # G1_FAULT = 8
write_u32 96 0x00100000  # 舵机 ERROR 0x10
if "$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 5 --target 3000 \
  --speed-raw 500 --time-raw 10 --execute >"$build_dir/g2-precommit.out" 2>&1; then
  echo 'Single-axis CLI accepted a pre-commit read fault' >&2; exit 1
fi
grep -q 'write_sent=0 .*phase=pre_commit' "$build_dir/g2-precommit.out"
grep -q '本次没有发出任何运动帧' "$build_dir/g2-precommit.out"
if grep -q '运动帧已被舵机接受' "$build_dir/g2-precommit.out"; then
  echo 'Pre-commit fault was mislabelled as an accepted motion frame' >&2; exit 1
fi
write_u32 100 0
write_u32 96 0

# Release remains a distinct 0x28<-0 request through the G1 whitelist.
write_u32 128 0
write_u32 92 2
write_u32 96 0
"$build_dir/rtcs-pl-g2-host" --uio "$mock" release --id 1 --execute \
  >"$build_dir/g2-release.out"
grep -q 'RTCS_PL_G2_RELEASE id=1 torque=OFF torque_register=0x28 value=0' \
  "$build_dir/g2-release.out"
[[ $(read_u32 84) == 9 ]]
[[ $(read_u32 128) == 0 ]]

# 卸力对所有轴开放：操作者需要卸载某一轴才能不带载做机械检查。
write_u32 128 0
write_u32 92 2
write_u32 96 0
"$build_dir/rtcs-pl-g2-host" --uio "$mock" release --id 5 --execute \
  >"$build_dir/g2-release-5.out"
grep -q 'RTCS_PL_G2_RELEASE id=5 torque=OFF torque_register=0x28 value=0' \
  "$build_dir/g2-release-5.out"
[[ $(read_u32 84) == 9 ]]
[[ $(read_u32 80) == 5 ]]
if "$build_dir/rtcs-pl-g2-host" --uio "$mock" release --id 7 --execute \
  >"$build_dir/g2-release-7.out" 2>&1; then
  echo 'Torque release accepted an out-of-range ID' >&2; exit 1
fi
grep -q 'ERR ID must be 1..6 for torque release' "$build_dir/g2-release-7.out"
echo RTCS_PL_G2_CLI_GUARD_PASS
