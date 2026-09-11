## AX7020 约束模板。第 0 阶段的 100 MHz AXI 时钟来自 PS FCLK0，
## Vivado Block Design 自动携带时钟约束；这里不再对不存在的顶层端口建时钟。
## 此文件未经 G0 核验时，不得添加或连接任何真实舵机 IO。

## 仅为示例：G0 核验后，以真实引脚和电压标准替换 <PIN>。
## set_property PACKAGE_PIN <PIN> [get_ports servo_rx]
## set_property IOSTANDARD LVCMOS33 [get_ports servo_rx]
## set_property PACKAGE_PIN <PIN> [get_ports servo_tx]
## set_property IOSTANDARD LVCMOS33 [get_ports servo_tx]
## set_property PACKAGE_PIN <PIN> [get_ports servo_tx_en]
## set_property IOSTANDARD LVCMOS33 [get_ports servo_tx_en]
