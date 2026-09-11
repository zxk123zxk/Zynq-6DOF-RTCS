# Creates the AX7Z020B PS-PL baseline in the current Vivado project.
if {[llength [get_bd_designs -quiet rtcs_system]] != 0} {
  current_bd_design rtcs_system
  return
}

create_bd_design rtcs_system
set ps7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
source [file join [file dirname [info script]] ax7z020b_ps7_config.tcl]
apply_ax7z020b_ps7_config processing_system7_0

set axi [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 ps7_axi_periph]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $axi

set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps7_0_100m]
set rtcs [create_bd_cell -type module -reference rtcs_axi_wrapper_bd rtcs_axi_wrapper_0]

set irq_concat [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 irq_concat_0]
set_property -dict [list CONFIG.NUM_PORTS {2} CONFIG.IN0_WIDTH {1} CONFIG.IN1_WIDTH {15}] $irq_concat
set irq_zero [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 irq_zero_0]
set_property -dict [list CONFIG.CONST_WIDTH {15} CONFIG.CONST_VAL {0}] $irq_zero

set ddr [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:ddrx_rtl:1.0 DDR]
set fixed_io [create_bd_intf_port -mode Master -vlnv xilinx.com:display_processing_system7:fixedio_rtl:1.0 FIXED_IO]
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/DDR] [get_bd_intf_ports DDR]
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/FIXED_IO] [get_bd_intf_ports FIXED_IO]
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins ps7_axi_periph/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins ps7_axi_periph/M00_AXI] [get_bd_intf_pins rtcs_axi_wrapper_0/S_AXI]

connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
  [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] \
  [get_bd_pins ps7_axi_periph/ACLK] \
  [get_bd_pins ps7_axi_periph/S00_ACLK] \
  [get_bd_pins ps7_axi_periph/M00_ACLK] \
  [get_bd_pins rtcs_axi_wrapper_0/s_axi_aclk] \
  [get_bd_pins rst_ps7_0_100m/slowest_sync_clk]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins rst_ps7_0_100m/ext_reset_in]
connect_bd_net [get_bd_pins rst_ps7_0_100m/interconnect_aresetn] [get_bd_pins ps7_axi_periph/ARESETN]
connect_bd_net [get_bd_pins rst_ps7_0_100m/peripheral_aresetn] \
  [get_bd_pins ps7_axi_periph/S00_ARESETN] \
  [get_bd_pins ps7_axi_periph/M00_ARESETN] \
  [get_bd_pins rtcs_axi_wrapper_0/s_axi_aresetn]
connect_bd_net [get_bd_pins rtcs_axi_wrapper_0/irq] [get_bd_pins irq_concat_0/In0]
connect_bd_net [get_bd_pins irq_zero_0/dout] [get_bd_pins irq_concat_0/In1]
connect_bd_net [get_bd_pins irq_concat_0/dout] [get_bd_pins processing_system7_0/IRQ_F2P]

set rtcs_segment [lindex [get_bd_addr_segs -of_objects [get_bd_intf_pins rtcs_axi_wrapper_0/S_AXI]] 0]
if {$rtcs_segment eq ""} { error "RTCS AXI address segment was not inferred" }
assign_bd_address -offset 0x43C00000 -range 64K \
  -target_address_space [get_bd_addr_spaces processing_system7_0/Data] $rtcs_segment -force

validate_bd_design
save_bd_design
generate_target all [get_files [get_property FILE_NAME [get_bd_designs rtcs_system]]]
make_wrapper -files [get_files [get_property FILE_NAME [get_bd_designs rtcs_system]]] -top
set bd_wrapper [file join $project_dir "${project_name}.gen" sources_1 bd rtcs_system hdl rtcs_system_wrapper.v]
if {![file exists $bd_wrapper]} { error "Generated BD wrapper was not found: $bd_wrapper" }
add_files -norecurse $bd_wrapper
set_property top rtcs_system_wrapper [current_fileset]
update_compile_order -fileset sources_1
