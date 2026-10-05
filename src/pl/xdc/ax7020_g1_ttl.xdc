# AX7Z020B J20 / Bank34. No board or servo supply is exported here.
set_property PACKAGE_PIN V15 [get_ports servo_ttl_tx]
set_property IOSTANDARD LVCMOS33 [get_ports servo_ttl_tx]
set_property PACKAGE_PIN U20 [get_ports servo_ttl_rx]
set_property IOSTANDARD LVCMOS33 [get_ports servo_ttl_rx]
set_property PULLUP true [get_ports servo_ttl_rx]
set_property PACKAGE_PIN W15 [get_ports g1_inhibit]
set_property IOSTANDARD LVCMOS33 [get_ports g1_inhibit]
set_property PULLUP true [get_ports g1_inhibit]
