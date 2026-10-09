#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"
common=(
  src/pl/rtl/rtcs_pkg.sv src/pl/rtl/g2_board_limits_pkg.sv src/pl/rtl/hx30hm_protocol_pkg.sv
  src/pl/rtl/axi_lite_regs.sv src/pl/rtl/uart_byte_tx.sv
  src/pl/rtl/uart_byte_rx.sv src/pl/rtl/hx30hm_g1_engine.sv
  src/pl/rtl/servo_bus_master.sv src/pl/rtl/g2_descriptor_guard.sv
  src/pl/rtl/g2_six_axis_controller.sv
  src/pl/rtl/rtcs_top.sv src/pl/rtl/rtcs_axi_wrapper_bd.v
  src/pl/rtl/rtcs_axi_wrapper_ttl_bd.v
)
for top in tb_axi_lite_regs tb_hx30hm_protocol tb_hx30hm_g1_engine \
           tb_rtcs_g1_safe_top tb_rtcs_g1_ttl_top tb_g2_descriptor_guard \
           tb_g2_six_axis_controller tb_g2_cal_log_overflow \
           tb_g2_board_limits; do
  if ! verilator --binary --timing -Wno-fatal --top-module "$top" \
    --Mdir "build/sim/obj_$top" "${common[@]}" "sim/$top.sv" \
    >"build/sim/$top.compile.log" 2>&1; then
    tail -n 80 "build/sim/$top.compile.log" >&2
    exit 1
  fi
  "build/sim/obj_$top/V$top"
done
bash sim/run_g2_one_servo.sh
bash sim/run_pl_g1_cli_abi.sh
bash sim/run_pl_g2_cli_guard.sh
bash sim/run_pl_g2_six_cli_guard.sh
echo RTCS_WSL_REGRESSION_PASS
