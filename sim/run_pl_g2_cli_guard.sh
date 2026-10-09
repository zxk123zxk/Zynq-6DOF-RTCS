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
write_u32 0 0x5254000c
write_u32 92 8
"$build_dir/rtcs-pl-g2-host" --uio "$mock" probe |
  grep -q 'abi=0x5254000c physical_tx=DISABLED'
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

write_u32 132 0x300d2 # DONE | SENT | start/feedback/ACK/change validity
write_u32 140 2100
write_u32 276 2000
"$build_dir/rtcs-pl-g2-host" "${args[@]}" --execute >"$build_dir/g2-move.out"
grep -q 'commit id=1 target=2100 speed_raw=500 time_raw=22136 tolerance=30 observe_ms=5000 torque_toggle=0x28:1' \
  "$build_dir/g2-move.out"
grep -q 'RTCS_PL_G2_OK id=1 target=2100 position_raw=2100' "$build_dir/g2-move.out"
[[ $(read_u32 108) == $((0x0032001e)) ]] # 5 s, tolerance 30
[[ $(read_u32 112) == 2100 ]]
[[ $(read_u32 116) == $((0x56780000+500)) ]]
[[ $(read_u32 128) == 1194459137 ]]

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
write_u32 132 0x300f2 # DONE | SENT | LATE | result validity
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

write_u32 132 0x300d6 # current command fault, WRITE ACK and position change present
write_u32 136 9
write_u32 276 871
write_u32 140 880
if "$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 2 --target 891 \
    --speed-raw 500 --time-raw 10 --tolerance 5 --execute \
    >"$build_dir/g2-partial.out" 2>&1; then
  echo 'Partial movement outside tolerance was accepted' >&2; exit 1
fi
grep -q 'actual_delta=9 target_error=11 position_change_observed=1 in_band=0' "$build_dir/g2-partial.out"
grep -q 'ERR g2_fault=9 fault_id=2 write_sent=1 unicast_ack=1 position_feedback_valid=1' "$build_dir/g2-partial.out"
grep -q 'write_sent=1 unicast_ack=1 fault=9 fault_id=2' "$build_dir/g2-partial.out"
write_u32 132 0x100d6 # no observed position change
write_u32 136 16
write_u32 276 2080
write_u32 140 2080
if "$build_dir/rtcs-pl-g2-host" --uio "$mock" move --id 1 --target 2100 \
    --speed-raw 500 --time-raw 10 --execute >"$build_dir/g2-static.out" 2>&1; then
  echo 'In-band static feedback was accepted' >&2; exit 1
fi
grep -q 'actual_delta=0 target_error=20 position_change_observed=0 in_band=1' "$build_dir/g2-static.out"
grep -q 'ERR g2_fault=16' "$build_dir/g2-static.out"

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
echo RTCS_PL_G2_CLI_GUARD_PASS
