# Zynq PS-PL Heterogeneous Real-Time 6-DoF Robot Controller（Zynq PS-PL 异构实时六自由度机械臂控制器）

面向柔性制造动态纠错的 Zynq PS-PL 异构六轴机械臂实时控制系统。

本仓库从一开始按 **AMD 2026 FPGA 创新设计赛道自主选题（初级组）** 的可复现交付要求组织：源码、仿真、构建脚本、上板记录、性能数据和可复用 skill 均有固定位置。目标平台是 ALINX AX7020（XC7Z020），执行器为 6 个 HX-30HM 半双工总线舵机。

## 当前状态

PL 直连 G1 已由用户在 ABI 02/03 镜像上完成 ID 1 只读实物验收。ABI 04 的首次 ID 1 试动未在原 2 秒期限内通过（`fault=9`、末次反馈1999；随后独立 READ 为2006）。ABI 05 上板预读2006后因起点窗口不符而拒绝，未发送 WRITE；其构建产物已归档。ABI 06 已上板：ABI、禁发、一次性状态与预读 `2005` 全部通过，WRITE 帧 `FF FF 01 09 03 2A CE 07 00 00 32 00 C1` 已发出且被舵机应答 `ERROR=0`，但 5 s 内 99 次反馈仍为 `2005`、无可见运动、报 `fault=9`。定因见下。

**当前源码 ABI `0x5254000C`**：实际 `-Ttl` 顶层保留 ID 1–6 安装状态的实测闭区间、参考位置和原始速度上限 1500，`calibrated_mask=0x3f`。六轴 SYNC、单轴与标定在 PL 发前检查参数；命令故障只报告本次结果，不永久闭锁后续显式命令。新结果诊断分开报告 WRITE、单播 ACK、现场起点、位置变化和最终误差，容差与观察期可配置。ID 2/6 的参考位置在限位下端，ID 3/4 在上端，均不是自动安全回位姿态。详见 [ABI 12 契约](docs/g2-abi12-registers.md)、[G2 阶段说明](docs/2.G2-six-axis-calibration.md)和 [SD 操作说明](docs/SD启动与项目迭代操作说明.md)。ABI 11 旧产物及哈希已[归档](artifacts/archive/g2-six-abi11-pre-abi12-20261008/README.md)。六轴板端同步运动、停止和急停验收仍由用户执行。

ABI 07 已有板端记录：预读 `2026`，目标 `2080`，实际移动后反馈停在 `2064`，未到位；线缆阻挡尚未证实。ABI 07 成套镜像已归档；当前板端步骤见 [SD 启动与迭代操作说明](docs/SD启动与项目迭代操作说明.md)。**上板运动由用户执行**。

ID 1 ABI 08 实物试动已通过：目标 2000，1.058 秒完成三次到位确认，最终误差 10 count；随后独立 READ 为 2001。板端六轴实测验收尚未完成。当前可用 SD 三件套及哈希见 [SHA256SUMS](artifacts/sd/SHA256SUMS)，上板运动由用户执行。

- PS：提供 Linux UIO/MMIO C++ 控制程序的最小可编译骨架及统一寄存器定义。
- PL：提供 AXI4-Lite 控制面、时钟计数器及共享半双工 G1/G2 引擎；默认构建不导出舵机 IO，`-Ttl` 构建用 V15 RX、U20 三态 TX、W15 上拉禁发输入。实际 `-Ttl` 顶层编入六轴实测限位；通用 RTL 仍默认未标定。
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

The default build keeps servo TX disabled. The `-Ttl` build requires a separate physical J20-36/W15→J20-38/GND strap to enable bus commands; the independent servo power switch remains separate.（默认构建禁用舵机 TX；直连版需本地硬件允许跳线，且独立舵机电源开关不由软件代替。）ABI 06–09 沿用同一套 BusLinker 丝印接线：J20-35/V15←TX、J20-33/U20→RX、J20-37↔GND；旧 ABI 的接法不同，详见 SD 操作说明。

旧 G1 镜像及测试证据见 [归档](artifacts/archive/g1-u20-inhibit-abi02-20261005/MANIFEST.md)。新镜像的首次上板步骤只在不接 BusLinker 时检查 `probe` 的版本及禁发跳线状态，见 [SD 操作说明](docs/SD启动与项目迭代操作说明.md)。

## Tooling decision（工具链决策）

Vitis HLS C++ is allowed by the contest, and can later implement an isolated numeric block such as the trapezoidal-profile kernel. It is **not** a replacement for manual RTL here: AXI integration, 1 Mbps half-duplex UART framing/arbitration, packet parser, watchdog, E-stop and deterministic multi-axis scheduling must remain reviewable RTL. The PS Linux controller is ordinary cross-compiled C++, not C++ automatically converted to all PL logic.（竞赛允许 Vitis HLS C++，后续可用于梯形轨迹内核等独立数值模块；但它**不能**替代这里的手写 RTL：AXI 集成、1 Mbps 半双工 UART 封装/仲裁、包解析器、看门狗、急停和确定性多轴调度均须保留为可审查的 RTL。PS Linux 控制器是普通交叉编译 C++，不会自动转换为全部 PL 逻辑。）

## License（许可证）

License selection is intentionally deferred until external reference code and competition submission terms have been reviewed. New project code should remain independently authored.（许可证选择刻意延后，待审查外部参考代码和竞赛提交条款后再决定；新增项目代码应保持独立创作。）
