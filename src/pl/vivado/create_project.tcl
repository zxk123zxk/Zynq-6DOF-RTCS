# AX7Z020B 可复现 PS-PL 项目。此脚本只生成硬件工程；PetaLinux
# 通过 src/ps/petalinux/ 下的脚本从其导出的 XSA 创建。
set script_dir [file dirname [file normalize [info script]]]
set project_root [file normalize "$script_dir/../../.."]
set project_name zynq_rtcs
set artifacts_dir [file join $project_root artifacts]
set project_dir [file join $artifacts_dir vivado $project_name]
set part xc7z020clg400-2

foreach subdir {vivado hw reports sd logs sim} {
  file mkdir [file join $artifacts_dir $subdir]
}

create_project $project_name $project_dir -part $part -force
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]

# 加入所有可综合 RTL；PS7 和 AXI 互连仍需在 Vivado 中显式配置。
# Module-reference Block Design cells must have a Verilog (.v) top file in
# Vivado 2023.2.  The wrapper instantiates the SystemVerilog RTCS core.
set rtl_files [glob -nocomplain "$project_root/src/pl/rtl/*.sv"]
set verilog_files [glob -nocomplain "$project_root/src/pl/rtl/*.v"]
if {[llength $rtl_files] == 0 || [llength $verilog_files] == 0} {
  error "Missing RTCS RTL source files under $project_root/src/pl/rtl"
}
add_files $rtl_files
add_files $verilog_files
add_files -fileset constrs_1 "$project_root/src/pl/xdc/ax7020_template.xdc"
source "$script_dir/create_rtcs_system.tcl"

puts "已创建 AX7Z020B PS7/AXI 基础工程：FCLK0=100 MHz，RTCS=0x43C00000/64 KiB。"
puts "该版本不导出舵机 IO，servo_tx_en 保持硬性禁用。"

# Use `vivado -mode batch -source create_project.tcl -tclargs build` on a
# machine where a complete hardware build is desired.  Keeping this opt-in
# makes ordinary source/BD validation quick and repeatable.
if {[lsearch -exact $argv build] >= 0} {
  set hw_dir [file join $artifacts_dir hw]
  set reports_dir [file join $artifacts_dir reports]
  launch_runs impl_1 -to_step write_bitstream -jobs 4
  wait_on_run impl_1
  set impl_status [get_property STATUS [get_runs impl_1]]
  if {$impl_status ne "write_bitstream Complete!"} {
    error "Implementation/bitstream failed: $impl_status; see $project_dir/$project_name.runs/impl_1/runme.log"
  }
  open_run impl_1
  report_timing_summary -file [file join $reports_dir timing_summary.rpt]
  report_utilization -file [file join $reports_dir utilization.rpt]
  report_methodology -file [file join $reports_dir methodology.rpt]
  set bit_file [file join $project_dir "${project_name}.runs" impl_1 rtcs_system_wrapper.bit]
  if {![file isfile $bit_file]} { error "Missing bitstream after implementation: $bit_file" }
  file copy -force $bit_file [file join $hw_dir rtcs_system.bit]
  set xsa_file [file join $hw_dir rtcs_system.xsa]
  write_hw_platform -fixed -include_bit -force -file $xsa_file
  if {![file isfile $xsa_file] || [file size $xsa_file] == 0} {
    error "XSA export failed or produced empty file: $xsa_file"
  }
  puts "RTCS_BUILD_OK XSA=$xsa_file bytes=[file size $xsa_file]"
}
