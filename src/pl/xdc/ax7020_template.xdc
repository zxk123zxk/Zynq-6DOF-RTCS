## AX7020 约束模板。G0/G1-USB 阶段的 100 MHz AXI 时钟来自 PS FCLK0，
## Vivado Block Design 自动携带时钟约束；这里不再对不存在的顶层端口建时钟。
## BusLinker USB 基线使用 PS USB0（MIO28..39），无 PL 顶层端口，因而不需增加 XDC。
## 此文件未经物理层核验时，不得添加或连接任何真实舵机 PL IO。

## 仅为示例：G0 核验后，以真实引脚和电压标准替换 <PIN>。
## set_property PACKAGE_PIN <PIN> [get_ports servo_rx]
## set_property IOSTANDARD LVCMOS33 [get_ports servo_rx]
## set_property PACKAGE_PIN <PIN> [get_ports servo_tx]
## set_property IOSTANDARD LVCMOS33 [get_ports servo_tx]
## set_property PACKAGE_PIN <PIN> [get_ports servo_tx_en]
## set_property IOSTANDARD LVCMOS33 [get_ports servo_tx_en]
