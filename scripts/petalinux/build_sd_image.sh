#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <petalinux-project-dir> <sd-output-dir>" >&2
  exit 64
fi

: "${PETALINUX:?Source the PetaLinux 2023.2 settings script first.}"
project_dir=$(realpath "$1")
sd_output=$(realpath -m "$2")

petalinux-build --project "$project_dir"
petalinux-package --boot --project "$project_dir" --force \
  --fsbl "$project_dir/images/linux/zynq_fsbl.elf" \
  --fpga "$project_dir/images/linux/system.bit" \
  --u-boot "$project_dir/images/linux/u-boot.elf"

mkdir -p "$sd_output"
install -m 0644 "$project_dir/images/linux/BOOT.BIN" "$sd_output/BOOT.BIN"
install -m 0644 "$project_dir/images/linux/image.ub" "$sd_output/image.ub"
mkimage -A arm -T script -C none -n "RTCS G0 SD boot" \
  -d "$(dirname "$0")/boot.cmd" "$sd_output/boot.scr"
sha256sum "$sd_output"/* | tee "$sd_output/SHA256SUMS"
echo "Copy these files to a FAT32 microSD boot partition: $sd_output"
