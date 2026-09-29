#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 </dev/ttyACMn|/dev/ttyUSBn> <servo-id-1..253> <writable-log-dir-mounted-from-artifacts/logs>" >&2
  exit 64
fi
device=$1
servo_id=$2
log_dir=$3
if [[ ! $device =~ ^/dev/tty(ACM|USB)[0-9]+$ ]]; then
  echo "Unexpected USB serial device: $device" >&2
  exit 64
fi
if [[ ! $servo_id =~ ^[1-9][0-9]{0,2}$ ]]; then
  echo "Invalid explicit servo ID: $servo_id (expected 1..253)" >&2
  exit 64
fi
if (( servo_id > 253 )); then
  echo "Invalid explicit servo ID: $servo_id (expected 1..253)" >&2
  exit 64
fi
[[ -c $device ]] || { echo "Missing serial device: $device" >&2; exit 66; }
[[ -d $log_dir && -w $log_dir ]] || { echo "Log directory must be mounted/writable: $log_dir" >&2; exit 66; }
command -v rtcs-buslinker-g1 >/dev/null || { echo 'rtcs-buslinker-g1 absent from rootfs' >&2; exit 69; }
log="$log_dir/g1-readonly-$(date +%Y%m%d-%H%M%S).log"
{
  echo "G1 READ-ONLY: PS UART/SD boot/USB serial/ID=$servo_id PING and position READ"
  echo "uname=$(uname -a)"
  echo "console=$(cat /proc/cmdline)"
  driver_link="/sys/class/tty/${device##*/}/device/driver"
  if [[ ! -L $driver_link || ! -e $driver_link ]]; then
    echo "ERR driver symlink missing or dangling: $driver_link"
    exit 1
  fi
  driver=$(basename "$(readlink -f "$driver_link")")
  echo "device=$device driver=$driver"
  dmesg | grep -Ei 'usb|cdc_acm|ch341|ttyACM|ttyUSB|mmc|ttyPS' | tail -n 50 || true
  if [[ $device == /dev/ttyACM* && $driver != cdc_acm ]]; then
    echo "ERR $device is not bound to cdc_acm (driver=$driver)"
    exit 1
  fi
  if [[ $device == /dev/ttyUSB* && $driver != ch341 ]]; then
    echo "ERR $device is not bound to ch341 (driver=$driver)"
    exit 1
  fi
  stty -F "$device" 1000000 raw -echo -ixon -ixoff -crtscts cs8 -parenb -cstopb
  echo "termios=$(stty -F "$device" -a)"
  rtcs-buslinker-g1 --device "$device" --id "$servo_id" ping
  rtcs-buslinker-g1 --device "$device" --id "$servo_id" read-position
  echo 'G1_READONLY_PASS'
} 2>&1 | tee "$log"
echo "Log: $log"
