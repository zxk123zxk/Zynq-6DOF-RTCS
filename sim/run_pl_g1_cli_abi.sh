#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
build_dir="$repo_root/build/sim"
mkdir -p "$build_dir"
gcc -std=c11 -Wall -Wextra -Werror -O2 \
  "$repo_root/src/ps/linux/apps/rtcs_pl_g1.c" -o "$build_dir/rtcs-pl-g1-host"

old_image="$build_dir/g1-abi02.mock-uio"
new_image="$build_dir/g1-abi12.mock-uio"
truncate -s 65536 "$old_image"
truncate -s 65536 "$new_image"
printf '\002\000\124\122' | dd of="$old_image" bs=1 seek=0 conv=notrunc status=none
printf '\014\000\124\122' | dd of="$new_image" bs=1 seek=0 conv=notrunc status=none
printf '\010\000\000\000' | dd of="$new_image" bs=1 seek=92 conv=notrunc status=none

if "$build_dir/rtcs-pl-g1-host" --uio "$old_image" probe > "$build_dir/g1-old-abi.stdout" 2> "$build_dir/g1-old-abi.stderr"; then
  echo 'Old pinout ABI was accepted' >&2
  exit 1
fi
grep -q 'ERR incompatible_pl_id .*expected=0x5254000c' "$build_dir/g1-old-abi.stderr"
"$build_dir/rtcs-pl-g1-host" --uio "$new_image" probe > "$build_dir/g1-new-abi.stdout"
grep -q 'id_version=0x5254000c .*physical_tx=DISABLED' "$build_dir/g1-new-abi.stdout"
if "$build_dir/rtcs-pl-g1-host" --uio "$new_image" --id 1 ping > "$build_dir/g1-disabled.stdout" 2> "$build_dir/g1-disabled.stderr"; then
  echo 'Disabled physical TX accepted PING' >&2
  exit 1
fi
grep -q 'ERR physical_tx_disabled; check J20-36 to J20-38' "$build_dir/g1-disabled.stderr"
echo 'RTCS_PL_G1_CLI_ABI_PASS'
