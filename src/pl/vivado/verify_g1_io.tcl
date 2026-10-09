set script_dir [file dirname [file normalize [info script]]]
set root [file normalize "$script_dir/../../.."]
open_project [file join $root artifacts vivado zynq_rtcs zynq_rtcs.xpr]
open_run impl_1
foreach {port expected_pin} {servo_ttl_tx U20 servo_ttl_rx V15 g1_inhibit W15} {
  set actual_pin [get_property PACKAGE_PIN [get_ports $port]]
  if {$actual_pin ne $expected_pin} {
    error "G1 TTL port $port is on $actual_pin, expected $expected_pin"
  }
  set io_standard [get_property IOSTANDARD [get_ports $port]]
  if {$io_standard ne "LVCMOS33"} {
    error "G1 TTL port $port uses $io_standard, expected LVCMOS33"
  }
}
set tristates [get_cells -hier -filter {REF_NAME == OBUFT}]
if {[llength $tristates] != 1} {
  error "G1 TTL requires exactly one OBUFT; found [llength $tristates]"
}
if {![string is true -strict [get_property PULLUP [get_ports g1_inhibit]]]} {
  error "G1 inhibit W15 must have an enabled internal PULLUP"
}
if {![string is true -strict [get_property PULLUP [get_ports servo_ttl_rx]]]} {
  error "G1 RX V15 must have an enabled internal PULLUP"
}
set report_path [file join $root artifacts reports g1_ttl_io.rpt]
report_io -file $report_path
puts "RTCS_G1_TTL_IO_OK tx=U20 rx=V15 inhibit=W15 pullup=TRUE obuft=[llength $tristates] report=$report_path"
