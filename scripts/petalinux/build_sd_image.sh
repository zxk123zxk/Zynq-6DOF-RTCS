#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <existing-petalinux-project-dir>" >&2
  exit 64
fi

: "${PETALINUX:?Source the PetaLinux 2023.2 settings script first.}"
for tool in petalinux-build petalinux-package mkimage sha256sum; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 69; }
done
project_dir=$(realpath "$1")
repo_root=$(realpath "$(dirname "$0")/../..")
sd_output="$repo_root/artifacts/sd"
logs_dir="$repo_root/artifacts/logs"
xsa_path="$repo_root/artifacts/hw/rtcs_system.xsa"
[[ -d "$project_dir/project-spec" ]] || { echo "Not a PetaLinux project: $project_dir" >&2; exit 66; }
[[ -s "$xsa_path" ]] || { echo "Missing XSA: $xsa_path" >&2; exit 66; }
mkdir -p "$sd_output" "$logs_dir"
cd "$project_dir"

petalinux-build --project "$project_dir" 2>&1 | tee "$logs_dir/petalinux-build.log"
shopt -s nullglob
kernel_configs=("$project_dir"/build/tmp/work/*/linux-xlnx/*/linux-*-build/.config)
if [[ ${#kernel_configs[@]} -eq 0 ]]; then
  echo 'Final PetaLinux kernel .config not found; refusing to package SD image' >&2
  exit 65
fi
if ! grep -qx 'CONFIG_USB_ACM=y' "${kernel_configs[0]}"; then
  echo "CONFIG_USB_ACM=y absent from final kernel .config: ${kernel_configs[0]}" >&2
  exit 65
fi
if ! grep -qx 'CONFIG_USB_SERIAL_CH341=y' "${kernel_configs[0]}"; then
  echo "CONFIG_USB_SERIAL_CH341=y absent from final kernel .config: ${kernel_configs[0]}" >&2
  exit 65
fi
for file in zynq_fsbl.elf system.bit u-boot.elf image.ub; do
  [[ -s "$project_dir/images/linux/$file" ]] || { echo "Missing build output: $file" >&2; exit 66; }
done
if ! cmp -s "$project_dir/images/linux/system.bit" "$repo_root/artifacts/hw/rtcs_system.bit"; then
  echo 'PetaLinux system.bit differs from artifacts/hw/rtcs_system.bit; refusing to package a stale bitstream' >&2
  exit 65
fi
petalinux-package --boot --project "$project_dir" --force \
  --fsbl "$project_dir/images/linux/zynq_fsbl.elf" \
  --fpga "$project_dir/images/linux/system.bit" \
  --u-boot "$project_dir/images/linux/u-boot.elf" 2>&1 | tee "$logs_dir/petalinux-package.log"

[[ -s "$project_dir/images/linux/BOOT.BIN" ]] || { echo 'Missing BOOT.BIN' >&2; exit 66; }
install -m 0644 "$project_dir/images/linux/BOOT.BIN" "$sd_output/BOOT.BIN"
install -m 0644 "$project_dir/images/linux/image.ub" "$sd_output/image.ub"
mkimage -A arm -T script -C none -n "RTCS SD boot" \
  -d "$repo_root/scripts/petalinux/boot.cmd" "$sd_output/boot.scr" 2>&1 | tee "$logs_dir/mkimage.log"
(cd "$sd_output" && sha256sum BOOT.BIN image.ub boot.scr > SHA256SUMS && sha256sum -c SHA256SUMS)
echo "RTCS_SD_OK $sd_output"
