#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || ( $1 != --import-hw && $1 != --sync-only ) ]]; then
  echo "usage: $0 <--import-hw|--sync-only> <petalinux-project-dir>" >&2
  exit 64
fi

: "${PETALINUX:?Source the PetaLinux 2023.2 settings script first.}"
mode=$1
project_dir=$(realpath -m "$2")
repo_root=$(realpath "$(dirname "$0")/../..")
xsa_path="$repo_root/artifacts/hw/rtcs_system.xsa"
created=0

if [[ $mode == --import-hw && ! -s "$xsa_path" ]]; then
  echo "XSA not found: $xsa_path" >&2
  exit 66
fi

if [[ ! -d "$project_dir" ]]; then
  if [[ $mode != --import-hw ]]; then echo "Existing project required: $project_dir" >&2; exit 66; fi
  mkdir -p "$(dirname "$project_dir")"
  (
    cd "$(dirname "$project_dir")"
    petalinux-create --type project --template zynq --name "$(basename "$project_dir")"
  )
  created=1
fi

if [[ $mode == --import-hw ]]; then
  (cd "$project_dir" && petalinux-config --silentconfig --get-hw-description "$(dirname "$xsa_path")" --project "$project_dir")
fi
[[ -d "$project_dir/project-spec/meta-user" ]] || { echo "Not a PetaLinux project: $project_dir" >&2; exit 66; }
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-apps/rtcs-uart-smoke/rtcs-uart-smoke.bb" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-uart-smoke/rtcs-uart-smoke.bb"
install -D -m 0644 "$repo_root/src/ps/linux/apps/rtcs_uart_smoke.c" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-uart-smoke/files/rtcs_uart_smoke.c"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-apps/rtcs-uart-loopback/rtcs-uart-loopback.bb" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-uart-loopback/rtcs-uart-loopback.bb"
install -D -m 0644 "$repo_root/src/ps/linux/apps/rtcs_uart_loopback.c" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-uart-loopback/files/rtcs_uart_loopback.c"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-apps/rtcs-buslinker-g1/rtcs-buslinker-g1.bb" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-buslinker-g1/rtcs-buslinker-g1.bb"
install -D -m 0644 "$repo_root/src/ps/linux/apps/rtcs_buslinker_g1.c" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-buslinker-g1/files/rtcs_buslinker_g1.c"
install -D -m 0755 "$repo_root/scripts/petalinux/g1_readonly_check.sh" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-buslinker-g1/files/g1_readonly_check.sh"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-apps/rtcs-pl-g1/rtcs-pl-g1.bb" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-pl-g1/rtcs-pl-g1.bb"
install -D -m 0644 "$repo_root/src/ps/linux/apps/rtcs_pl_g1.c" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-pl-g1/files/rtcs_pl_g1.c"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-apps/rtcs-pl-g2/rtcs-pl-g2.bb" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-pl-g2/rtcs-pl-g2.bb"
install -D -m 0644 "$repo_root/src/ps/linux/apps/rtcs_pl_g2.c" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-pl-g2/files/rtcs_pl_g2.c"
install -D -m 0644 "$repo_root/src/ps/linux/apps/rtcs_pl_g2_six.c" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-pl-g2/files/rtcs_pl_g2_six.c"
install -D -m 0644 "$repo_root/src/ps/linux/apps/rtcs_servo_diag.h" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-pl-g2/files/rtcs_servo_diag.h"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-core/images/petalinux-image-minimal.bbappend" \
  "$project_dir/project-spec/meta-user/recipes-core/images/petalinux-image-minimal.bbappend"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-bsp/device-tree/files/system-user.dtsi" \
  "$project_dir/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-kernel/linux/linux-xlnx/usbserial.cfg" \
  "$project_dir/project-spec/meta-user/recipes-kernel/linux/linux-xlnx/usbserial.cfg"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-kernel/linux/linux-xlnx/uio.cfg" \
  "$project_dir/project-spec/meta-user/recipes-kernel/linux/linux-xlnx/uio.cfg"
kernel_append="$project_dir/project-spec/meta-user/recipes-kernel/linux/linux-xlnx_%.bbappend"
if [[ ! -e "$kernel_append" ]]; then
  install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-kernel/linux/linux-xlnx_%.bbappend" "$kernel_append"
else
  grep -qF 'FILESEXTRAPATHS:prepend' "$kernel_append" || \
    printf '\nFILESEXTRAPATHS:prepend := "${THISDIR}/linux-xlnx:"\n' >> "$kernel_append"
  grep -qF 'file://usbserial.cfg' "$kernel_append" || \
    printf '\nSRC_URI += "file://usbserial.cfg"\n' >> "$kernel_append"
  grep -qF 'file://uio.cfg' "$kernel_append" || \
    printf '\nSRC_URI += "file://uio.cfg"\n' >> "$kernel_append"
  grep -qF 'KERNEL_MODULE_AUTOLOAD += "uio_pdrv_genirq"' "$kernel_append" || \
    printf '\nKERNEL_MODULE_AUTOLOAD += "uio_pdrv_genirq"\n' >> "$kernel_append"
  grep -qF 'KERNEL_MODULE_PROBECONF += "uio_pdrv_genirq"' "$kernel_append" || \
    printf '\nKERNEL_MODULE_PROBECONF += "uio_pdrv_genirq"\n' >> "$kernel_append"
  grep -qF 'module_conf_uio_pdrv_genirq = "options uio_pdrv_genirq of_id=generic-uio"' "$kernel_append" || \
    printf '\nmodule_conf_uio_pdrv_genirq = "options uio_pdrv_genirq of_id=generic-uio"\n' >> "$kernel_append"
fi
rootfs_config="$project_dir/project-spec/meta-user/conf/user-rootfsconfig"
mkdir -p "$(dirname "$rootfs_config")"
touch "$rootfs_config"
# user-rootfsconfig defines menu entries; selected values live in rootfs_config.
sed -i 's/\r$//; s/^\(CONFIG_rtcs-\(uart-smoke\|uart-loopback\|buslinker-g1\|pl-g1\|pl-g2\)\)=y$/\1/' "$rootfs_config"
for package in rtcs-uart-smoke rtcs-uart-loopback rtcs-buslinker-g1 rtcs-pl-g1 rtcs-pl-g2; do
  grep -qxF "CONFIG_$package" "$rootfs_config" || printf 'CONFIG_%s\n' "$package" >> "$rootfs_config"
done
awk '/^CONFIG_rtcs-(uart-smoke|uart-loopback|buslinker-g1|pl-g1|pl-g2)$/ { if (seen[$0]++) next } { print }' "$rootfs_config" > "$rootfs_config.tmp"
mv "$rootfs_config.tmp" "$rootfs_config"
while IFS= read -r -d '' generated_kconfig; do
  sed -i 's/\r$//; s/^\(CONFIG_rtcs-\(uart-smoke\|uart-loopback\|buslinker-g1\|pl-g1\|pl-g2\)\)=y$/\1/' "$generated_kconfig"
done < <(find "$project_dir" -name Kconfig.user -type f -print0)
if [[ $created == 1 ]]; then
  selections="$project_dir/project-spec/configs/rootfs_config"
  touch "$selections"
  for package in rtcs-uart-smoke rtcs-uart-loopback rtcs-buslinker-g1 rtcs-pl-g1 rtcs-pl-g2; do
    grep -qxF "CONFIG_$package=y" "$selections" || printf 'CONFIG_%s=y\n' "$package" >> "$selections"
  done
fi
selections="$project_dir/project-spec/configs/rootfs_config"
mkdir -p "$(dirname "$selections")"
touch "$selections"
sed -i '/^# CONFIG_rtcs-pl-g1 is not set$/d' "$selections"
grep -qxF 'CONFIG_rtcs-pl-g1=y' "$selections" || printf 'CONFIG_rtcs-pl-g1=y\n' >> "$selections"
sed -i '/^# CONFIG_rtcs-pl-g2 is not set$/d' "$selections"
grep -qxF 'CONFIG_rtcs-pl-g2=y' "$selections" || printf 'CONFIG_rtcs-pl-g2=y\n' >> "$selections"
echo "PetaLinux sync OK ($mode): $project_dir"
