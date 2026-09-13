#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <rtcs_system.xsa> <petalinux-project-dir>" >&2
  exit 64
fi

: "${PETALINUX:?Source the PetaLinux 2023.2 settings script first.}"
xsa_path=$(realpath "$1")
project_dir=$(realpath -m "$2")
repo_root=$(realpath "$(dirname "$0")/../..")

if [[ ! -f "$xsa_path" ]]; then
  echo "XSA not found: $xsa_path" >&2
  exit 66
fi

if [[ ! -d "$project_dir" ]]; then
  mkdir -p "$(dirname "$project_dir")"
  (
    cd "$(dirname "$project_dir")"
    petalinux-create --type project --template zynq --name "$(basename "$project_dir")"
  )
fi

petalinux-config --silentconfig --get-hw-description "$(dirname "$xsa_path")" --project "$project_dir"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-apps/rtcs-uart-smoke/rtcs-uart-smoke.bb" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-uart-smoke/rtcs-uart-smoke.bb"
install -D -m 0644 "$repo_root/src/ps/linux/apps/rtcs_uart_smoke.c" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-uart-smoke/files/rtcs_uart_smoke.c"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-apps/rtcs-uart-loopback/rtcs-uart-loopback.bb" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-uart-loopback/rtcs-uart-loopback.bb"
install -D -m 0644 "$repo_root/src/ps/linux/apps/rtcs_uart_loopback.c" \
  "$project_dir/project-spec/meta-user/recipes-apps/rtcs-uart-loopback/files/rtcs_uart_loopback.c"
install -D -m 0644 "$repo_root/src/ps/petalinux/meta-user/recipes-bsp/device-tree/files/system-user.dtsi" \
  "$project_dir/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi"
rootfs_config="$project_dir/project-spec/meta-user/conf/user-rootfsconfig"
grep -qxF 'CONFIG_rtcs-uart-smoke=y' "$rootfs_config" || \
  echo 'CONFIG_rtcs-uart-smoke=y' >> "$rootfs_config"
grep -qxF 'CONFIG_rtcs-uart-loopback=y' "$rootfs_config" || \
  echo 'CONFIG_rtcs-uart-loopback=y' >> "$rootfs_config"
echo "PetaLinux project prepared: $project_dir"
