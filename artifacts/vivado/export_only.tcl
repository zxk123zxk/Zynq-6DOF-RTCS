set repo {D:/3.Electronic_Information/2026.9-ES_Competition-FPGA-AMD/Zynq-6DOF-RTCS}
open_project [file join $repo artifacts vivado zynq_rtcs zynq_rtcs.xpr]
open_run impl_1
set bit_src [file join $repo artifacts vivado zynq_rtcs zynq_rtcs.runs impl_1 rtcs_system_wrapper.bit]
set bit_dst [file join $repo artifacts hw rtcs_system.bit]
set xsa_dst [file join $repo artifacts hw rtcs_system.xsa]
if {![file isfile $bit_src]} { error "missing bitstream $bit_src" }
file copy -force $bit_src $bit_dst
write_hw_platform -fixed -include_bit -force -file $xsa_dst
if {![file isfile $xsa_dst] || [file size $xsa_dst] == 0} { error "XSA export failed" }
puts "RTCS_EXPORT_OK bit=[file size $bit_dst] xsa=[file size $xsa_dst]"
