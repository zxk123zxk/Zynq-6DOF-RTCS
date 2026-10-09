# Zynq-6DOF-RTCS

AX7020（XC7Z020）PS/PL 六轴 HX-30HM 总线舵机控制工程。当前可上板硬件、Linux CLI 和 SD 镜像使用 **ABI 0x5254000C**。

## 阶段状态

| 阶段 | 状态 | 入口 |
| --- | --- | --- |
| G0 / G1 | 已通过基础启动和只读协议验收 | [总规划](docs/0.1hardware_bringup.md) |
| G2 | 操作者于 2026-10-09 确认六轴联动顺利执行并结束阶段；本仓库未收到该次完整终端日志及逐项 stop/急停记录 | [G2 总结与核心文件](docs/2.G2-six-axis-calibration.md) |
| G3 | 前期准备：固定工位点、夹爪角色和单循环数据待实测 | [G3 准备](docs/3.G3-static-closed-loop.md) |
| G4 | 未开始：动态视觉演示 | [G4 边界](docs/4.G4-dynamic-demo.md) |

G2 的实际 TTL 顶层编入六轴实测闭区间，原始速度上限 1500；PL 发前检查物理禁发、限位、截止时间和总线占用。一次显式提交最多发送一帧，不自动重试。六轴广播没有 ACK；CLI 分别报告 WRITE、现场起点、反馈位移与目标误差。测得的六轴参考位置不是安全自动回位姿态。接口定义见 [ABI 12 契约](docs/g2-abi12-registers.md)。

## 核心验收代码

在 WSL 中运行完整 RTL 与 CLI 离线回归：

    bash sim/run_regression_wsl.sh

板端先在物理禁发状态运行 probe 和 limits；装上 J20-36/W15 到 J20-38/GND 的允许跳线后再 inventory。六轴目标只能根据本次实时位置和机械空间显式填写；同步写、越限拒绝、stop 与独立断电急停的完整顺序见 [SD 操作说明](docs/SD启动与项目迭代操作说明.md)。板端运动不由构建脚本执行。

## 核心目录

| 目录 | 内容 |
| --- | --- |
| [src/pl/rtl/](src/pl/rtl/rtcs_top.sv) | AXI 寄存器、G2 六轴控制器、描述符检查、舵机协议与实际顶层 |
| [src/ps/linux/apps/](src/ps/linux/apps/rtcs_pl_g2_six.c) | G1、G2 单轴、G2 六轴 UIO CLI |
| [config/](config/g2_measured_limits.toml) | 安装状态实测限位和参考位置 |
| [sim/](sim/README.md) | RTL、CLI mock、完整离线回归 |
| [scripts/](scripts/build_vivado.ps1) | Vivado、XSA 导入和 PetaLinux SD 构建 |
| [artifacts/hw/](artifacts/hw/rtcs_system.xsa) 与 [artifacts/sd/](artifacts/sd/SHA256SUMS) | ABI 12 XSA、bitstream、SD 三件套及哈希 |
| [docs/history/](docs/history/README-through-G2-20261009.md) 与 [artifacts/archive/](artifacts/archive/) | 旧 ABI 操作记录和归档镜像 |

当前构建使用 Vivado 2023.2 与 PetaLinux 2023.2。默认构建不导出舵机 IO；实际 TTL 镜像须用 Vivado 脚本的 Build/Ttl 选项，并保留独立舵机电源与物理禁发。G3 的轨迹、FIFO、IRQ 和 100 次静态抓放尚未实现，不能视作本版能力。
