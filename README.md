# Zynq PS-PL Heterogeneous Real-Time 6-DoF Robot Controller（Zynq PS-PL 异构实时六自由度机械臂控制器）

面向柔性制造动态纠错的 Zynq PS-PL 异构六轴机械臂实时控制系统。

本仓库从一开始按 **AMD 2026 FPGA 创新设计赛道自主选题（初级组）** 的可复现交付要求组织：源码、仿真、构建脚本、上板记录、性能数据和可复用 skill 均有固定位置。目标平台是 ALINX AX7020（XC7Z020），执行器为 6 个 HX-30HM 半双工总线舵机。

## 当前状态

当前处于“G0 新镜像待实物复验、G1 只读 USB 通信待验收”：Vivado 实现、XSA 与寄存器/协议仿真已通过，但不是可驱动机械臂的完成品：

- PS：提供 Linux UIO/MMIO C++ 控制程序的最小可编译骨架及统一寄存器定义。
- PL：提供 AXI4-Lite 控制面、时钟计数器和模块边界；目前不导出舵机 IO，`servo_tx_en` 固定为零。
- 工程：已提供 AX7Z020B 的 Vivado 2023.2 PS7/AXI Block Design、PetaLinux 2023.2 构建脚本、PS UART1 Linux 冒烟程序、验证清单、寄存器契约与阶段验收标准。

不要把 `Material_Library/` 中的参考工程纳入本项目构建。`mycpu--` 是独立 RISC-V SoC 项目；KR260 工程面向 KR260、ROS2、USB 串口/PWM 机械臂，不能复用为 AX7020 的总线舵机控制器。

## Architecture（系统架构）

```text
USB camera -> PS Linux (vision / task FSM / FK-IK / deadline)
                | AXI4-Lite + IRQ
                v
PL (registers -> command FIFO -> trajectory -> safety -> servo bus)
                | 1 Mbps half-duplex UART
                v
6 x HX-30HM -> position/status feedback -> PL -> PS
```

（中文：USB 摄像头数据由 PS 上的 Linux 处理视觉、任务状态机、正逆运动学和截止时间；PS 经 AXI4-Lite 与中断同 PL 通信。PL 依次完成寄存器、命令队列、轨迹、安全和舵机总线工作；再经 1 Mbps 半双工 UART 连接六个 HX-30HM 舵机，位置/状态反馈沿相反方向返回。）

当前 G0 的核心改动见 [docs/0.G0-ps-pl-foundation.md](docs/0.G0-ps-pl-foundation.md)；后续阶段按 `docs/1.*` 至 `docs/4.*` 记录，统一门禁见 [docs/0.1hardware_bringup.md](docs/0.1hardware_bringup.md)。AXI 寄存器契约以 `src/pl/rtl/rtcs_pkg.sv` 和 `src/ps/linux/include/rtcs_registers.hpp` 为准。
当前八周学习、分工和验收计划见 [docs/team_eight_week_plan.md](docs/team_eight_week_plan.md)。

## Repository layout（仓库目录说明）

```text
src/pl/rtl/       Synthesizable SystemVerilog control-plane skeleton（可综合的 SystemVerilog 控制面骨架）
src/pl/xdc/       Board-specific constraints template（板级引脚约束模板）
src/pl/vivado/    Reproducible Vivado project script（可复现的 Vivado 工程脚本）
src/pl/hls/       Reserved only for a later trajectory HLS experiment（仅预留给后续轨迹 HLS 实验）
src/ps/linux/     PS Linux UIO C++ application skeleton（PS 端 Linux UIO C++ 应用骨架）
config/            Measured arm, bus and calibration data (not guesses)（实测的机械臂、总线与标定数据，不允许猜测）
sim/               RTL and protocol testbenches/results（RTL 与协议测试平台/结果）
scripts/           Build and verification helpers（构建与验证辅助脚本）
docs/              Architecture, bring-up and benchmark documentation（架构、上板和性能测试文档）
skill/             Reusable competition deliverable（可复用的竞赛交付技能）
```

## First build milestone（首次构建里程碑）

1. Windows: `powershell -ExecutionPolicy Bypass -File scripts/build_vivado.ps1 -Build`。生成物在 `artifacts/`，其中 XSA 固定为 `artifacts/hw/rtcs_system.xsa`。
2. WSL/PetaLinux 2023.2: 使用 `scripts/petalinux/create_project.sh --import-hw <现有项目目录>` 导入新 XSA，或用 `--sync-only` 只更新 Linux 源码；再调用 `scripts/petalinux/build_sd_image.sh <现有项目目录>`。
3. Boot the FAT32 SD image, log in at UART1 and run `rtcs-uart-smoke`.（由 FAT32 SD 卡启动，通过 UART1 登录后运行 `rtcs-uart-smoke`。）
4. Follow [docs/0.G0-ps-pl-foundation.md](docs/0.G0-ps-pl-foundation.md) and [docs/0.1hardware_bringup.md](docs/0.1hardware_bringup.md) before enabling any servo transmit signal.（启用任何舵机发送信号前，必须完成 G0 与上板总规划要求。）

The `servo_tx_en` output is intentionally hard-disabled in this revision. Its release is an explicit gate after electrical, protocol, packet-parser and emergency-stop tests pass.（本版本故意硬性禁用 `servo_tx_en` 输出；只有通过电气、协议、数据包解析器和急停测试后，才允许明确解锁。）

The locally installed Vivado 2023.2 was used only to parse/create the RTL shell. Before submission, reproduce synthesis, timing and board verification using the contest-recommended Vivado/Vitis 2025.2 or 2026.1 and record that version in the report.（本机安装的 Vivado 2023.2 仅用于解析/创建 RTL 骨架。提交前必须使用竞赛推荐的 Vivado/Vitis 2025.2 或 2026.1 复现综合、时序和板级验证，并将版本记录在报告中。）

## Tooling decision（工具链决策）

Vitis HLS C++ is allowed by the contest, and can later implement an isolated numeric block such as the trapezoidal-profile kernel. It is **not** a replacement for manual RTL here: AXI integration, 1 Mbps half-duplex UART framing/arbitration, packet parser, watchdog, E-stop and deterministic multi-axis scheduling must remain reviewable RTL. The PS Linux controller is ordinary cross-compiled C++, not C++ automatically converted to all PL logic.（竞赛允许 Vitis HLS C++，后续可用于梯形轨迹内核等独立数值模块；但它**不能**替代这里的手写 RTL：AXI 集成、1 Mbps 半双工 UART 封装/仲裁、包解析器、看门狗、急停和确定性多轴调度均须保留为可审查的 RTL。PS Linux 控制器是普通交叉编译 C++，不会自动转换为全部 PL 逻辑。）

## License（许可证）

License selection is intentionally deferred until external reference code and competition submission terms have been reviewed. New project code should remain independently authored.（许可证选择刻意延后，待审查外部参考代码和竞赛提交条款后再决定；新增项目代码应保持独立创作。）
