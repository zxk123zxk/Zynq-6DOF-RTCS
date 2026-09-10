# Zynq PS-PL Heterogeneous Real-Time 6-DoF Robot Controller

面向柔性制造动态纠错的 Zynq PS-PL 异构六轴机械臂实时控制系统。

本仓库从一开始按 **AMD 2026 FPGA 创新设计赛道自主选题（初级组）** 的可复现交付要求组织：源码、仿真、构建脚本、上板记录、性能数据和可复用 skill 均有固定位置。目标平台是 ALINX AX7020（XC7Z020），执行器为 6 个 HX-30HM 半双工总线舵机。

## 当前状态

这是第 0 阶段的安全工程骨架，不是可驱动机械臂的完成品：

- PS：提供 Linux UIO/MMIO C++ 控制程序的最小可编译骨架及统一寄存器定义。
- PL：提供 AXI4-Lite 控制面、时钟计数器和全部关键模块边界；执行器输出默认三态，绝不会在未完成协议和实机验证前误动作。
- 工程：提供 Vivado 建工程脚本、AX7020 约束模板、验证清单、寄存器契约与阶段验收标准。

不要把 `Material_Library/` 中的参考工程纳入本项目构建。`mycpu--` 是独立 RISC-V SoC 项目；KR260 工程面向 KR260、ROS2、USB 串口/PWM 机械臂，不能复用为 AX7020 的总线舵机控制器。

## Architecture

```text
USB camera -> PS Linux (vision / task FSM / FK-IK / deadline)
                | AXI4-Lite + IRQ
                v
PL (registers -> command FIFO -> trajectory -> safety -> servo bus)
                | 1 Mbps half-duplex UART
                v
6 x HX-30HM -> position/status feedback -> PL -> PS
```

模块职责、阶段边界和数据流见 [docs/architecture.md](docs/architecture.md)。AXI 寄存器契约见 [docs/register_map.md](docs/register_map.md)。

## Repository layout

```text
src/pl/rtl/       Synthesizable SystemVerilog control-plane skeleton
src/pl/xdc/       Board-specific constraints template
src/pl/vivado/    Reproducible Vivado project script
src/pl/hls/       Reserved only for a later trajectory HLS experiment
src/ps/linux/     PS Linux UIO C++ application skeleton
config/            Measured arm, bus and calibration data (not guesses)
sim/               RTL and protocol testbenches/results
scripts/           Build and verification helpers
docs/              Architecture, bring-up and benchmark documentation
skill/             Reusable competition deliverable
```

## First build milestone

1. In Vivado 2025.2 or 2026.1, run `src/pl/vivado/create_project.tcl`.
2. Add a Zynq-7000 Processing System IP and connect `M_AXI_GP0` to `rtcs_top/s_axi`; make the AXI clock/reset domains explicit.
3. Replace the placeholder XDC pin names with pins verified against the exact AX7020 schematic.
4. Build the PS tool with CMake and run `zynq_rtcs_ctl --dry-run`.
5. Follow [docs/hardware_bringup.md](docs/hardware_bringup.md) before enabling any servo transmit signal.

The `servo_tx_en` output is intentionally hard-disabled in this revision. Its release is an explicit gate after electrical, protocol, packet-parser and emergency-stop tests pass.

The locally installed Vivado 2023.2 was used only to parse/create the RTL shell. Before submission, reproduce synthesis, timing and board verification using the contest-recommended Vivado/Vitis 2025.2 or 2026.1 and record that version in the report.

## Tooling decision

Vitis HLS C++ is allowed by the contest, and can later implement an isolated numeric block such as the trapezoidal-profile kernel. It is **not** a replacement for manual RTL here: AXI integration, 1 Mbps half-duplex UART framing/arbitration, packet parser, watchdog, E-stop and deterministic multi-axis scheduling must remain reviewable RTL. The PS Linux controller is ordinary cross-compiled C++, not C++ automatically converted to all PL logic.

## License

License selection is intentionally deferred until external reference code and competition submission terms have been reviewed. New project code should remain independently authored.
