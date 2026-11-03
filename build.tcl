# 复现入口（与 report-1031.tex 附录 A 的命令一致）
#
#   vivado -mode batch -source build.tcl                  # 默认：TTL 版整建，产出 .bit + .xsa
#   vivado -mode batch -source build.tcl -tclargs base    # 只验证 BD/RTL，不导出舵机 IO
#
# 产物：
#   artifacts/hw/rtcs_system.bit
#   artifacts/hw/rtcs_system.xsa
#   artifacts/reports/{utilization,timing_summary,methodology}.rpt
#
# 默认带 ttl：板端实际运行的那版 bitstream 必须导出 servo_ttl_tx/rx 与 g1_inhibit 三个端口，
# 不带 ttl 的构建 servo_tx_en 硬禁发、舵机一根帧都收不到（见 README "构建"一节）。
# 真正的工程生成逻辑在 src/pl/vivado/create_project.tcl，本脚本只做参数归一与前置检查。

set script_dir [file dirname [file normalize [info script]]]
set rtl_dir [file join $script_dir src pl rtl]
set vivado_dir [file join $script_dir src pl vivado]

foreach required [list \
    [file join $vivado_dir create_project.tcl] \
    [file join $vivado_dir create_rtcs_system.tcl] \
    [file join $vivado_dir ax7z020b_ps7_config.tcl] \
    [file join $rtl_dir rtcs_top.sv]] {
  if {![file isfile $required]} {
    error "缺少构建设入文件：$required（请在仓库根目录执行本脚本）"
  }
}

set run_args $argv
if {[lsearch -exact $run_args base] >= 0} {
  set run_args [lsearch -all -inline -not -exact $run_args base]
} else {
  if {[lsearch -exact $run_args ttl] < 0} { lappend run_args ttl }
}
if {[lsearch -exact $run_args build] < 0} { lappend run_args build }
set argv $run_args

puts "RTCS_BUILD_ARGS $argv"
source [file join $vivado_dir create_project.tcl]
