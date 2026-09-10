## AX7020 constraint template. Pin locations and IOSTANDARD values are NOT
## filled in because they must be copied from the exact board schematic/manual.
## Do not synthesize or connect a live servo bus with this file unchanged.

create_clock -name pl_axi_clk -period 10.000 [get_ports s_axi_aclk]

## Example only -- replace <PIN> and voltage standard after G0 verification:
## set_property PACKAGE_PIN <PIN> [get_ports servo_rx]
## set_property IOSTANDARD LVCMOS33 [get_ports servo_rx]
## set_property PACKAGE_PIN <PIN> [get_ports servo_tx]
## set_property IOSTANDARD LVCMOS33 [get_ports servo_tx]
## set_property PACKAGE_PIN <PIN> [get_ports servo_tx_en]
## set_property IOSTANDARD LVCMOS33 [get_ports servo_tx_en]
