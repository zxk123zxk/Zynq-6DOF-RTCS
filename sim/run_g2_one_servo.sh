#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"
mkdir -p build/sim
if ! verilator --binary --timing -Wno-fatal --top-module tb_rtcs_g2_one_servo \
  --Mdir build/sim/obj_g2top \
  src/pl/rtl/rtcs_pkg.sv src/pl/rtl/hx30hm_protocol_pkg.sv \
  src/pl/rtl/axi_lite_regs.sv src/pl/rtl/uart_byte_tx.sv \
  src/pl/rtl/uart_byte_rx.sv src/pl/rtl/hx30hm_g1_engine.sv \
  src/pl/rtl/servo_bus_master.sv src/pl/rtl/g2_descriptor_guard.sv \
  src/pl/rtl/g2_six_axis_controller.sv src/pl/rtl/g2_board_limits_pkg.sv src/pl/rtl/rtcs_top.sv \
  sim/tb_rtcs_g2_one_servo.sv >build/sim/g2-one-servo.compile.log 2>&1; then
  tail -n 80 build/sim/g2-one-servo.compile.log >&2
  exit 1
fi
build/sim/obj_g2top/Vtb_rtcs_g2_one_servo
