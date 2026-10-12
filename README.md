# Zynq-6DOF-RTCS

AX7020（XC7Z020）PS/PL 六轴 HX-30HM 总线舵机控制工程。源码、XSA、bitstream 和仓库 SD 三件套为 ABI **0x5254000E**，**板端已于 2026-10-12 实测运行同一 ABI**（`physical_tx=ENABLED`）。**ID 1–5 为关节，ID 6 为夹爪**；**ID 5 的旧窄内部角度窗口已由官方软件重新校准并实测通过**。相机为幻尔 30 万像素 / 120° 广角 USB 免驱摄像头（无深度）。版本与哈希见[操作说明](docs/SD启动与项目迭代操作说明.md)。

> **流程约定：本仓库采用[双轨制](docs/0.1hardware_bringup.md)。** 竞赛轨只保留红线门禁（独立供电、物理禁发、PL 限位/速度/截止时间、独立硬件急停、实测标定、单帧提交、不自动重试），**任何流程性门禁不得阻塞竞赛轨的运动路径**；证据归档、逐步操作者确认、100 次循环与 P99 统计属归档轨，在周末补齐。冲刺日程与每日任务卡见 [docs/7.sprint-plan-daily-tasks.md](docs/7.sprint-plan-daily-tasks.md)。

## 阶段状态

| 阶段 | 状态 | 入口 |
| --- | --- | --- |
| G0 / G1 | 已通过基础启动和只读协议验收 | [总规划](docs/0.1hardware_bringup.md) |
| G2 | 已通过：六轴实测限位、参考位置与六轴同步运动；ABI 0E 上板，ID 5 单轴远端运动实测成功 | [G2 总结与原始证据](docs/2.G2-six-axis-calibration.md) |
| G3 | **进行中**：只读诊断已通过；夹爪确认为 ID 6；六步工位实测与连续自动循环待做 | [G3 静态闭环](docs/3.G3-static-closed-loop.md) |
| G4 | 未开始：相机标定与视觉引导静态抓取 | [G4 视觉静抓](docs/4.G4-static-vision-grasp.md) |
| G5 | 未开始：传送带动态抓取（预测拦截） | [G5 动态拦截](docs/5.G5-conveyor-dynamic.md) |
| G6 | 未开始：稳定性、性能度量与决赛交付 | [G6 交付](docs/6.G6-final-delivery.md) |

G2 的实际 TTL 顶层编入六轴命令闭区间（ID 5 的 0–4000 是**命令范围标注**，非机械全程实测；本阶段应补记真实区间），原始速度上限 1500；PL 发前检查物理禁发、目标限位、截止时间和总线占用。ABI 0E 的显式绝对目标单轴/六轴命令直接 WRITE，不先 READ 起点；发后仍检查单轴 ACK 或六轴逐轴稳定反馈，一次提交最多一帧、不自动重试。绝对运动的起点和实际位移显示 `UNAVAILABLE`，目标误差由发后有效位置计算。六轴广播没有 ACK。测得的六轴参考位置不是安全自动回位姿态。接口定义以 [PL 寄存器包](src/pl/rtl/rtcs_pkg.sv)和 [PS 头文件](src/ps/linux/include/rtcs_registers.hpp)为准。

ABI 13 起在运动故障时保存舵机 ERROR 原始字节及 ID（ABI 0E 保留），并配置 `uio_pdrv_genirq` 开机自动绑定 `generic-uio`。ABI 0E 删除了绝对运动的起点预读门槛——该门槛曾把舵机一个**瞬时** ERROR 位放大成跨命令粘滞的全局锁死，是本仓库历史上最严重的一次进度拖慢。[ID 5 旧窄窗口根因与 2026-10-12 重新校准实测](docs/2.G2-six-axis-calibration.md)已归档。竞赛轨按双轨制允许"一次授权、连续执行到失败即停"，但仍要求运动期间有人在场并能物理断电。

## 核心验收代码

在 WSL 中运行完整 RTL 与 CLI 离线回归：

    bash sim/run_regression_wsl.sh

新镜像上板后先在物理禁发状态运行 probe 和 limits；装上 J20-36/W15 到 J20-38/GND 的允许跳线后可只读 diagnose 与 torque-status。**2026-10-12 的六轴基线（`limits` + `diagnose` + `torque-status`）已全绿**，原始输出见 [G2 板端基线](docs/2.G2-six-axis-calibration.md)。注意上电后 `0x28=0`（卸力），不下扭矩开关舵机不会动。六轴目标只能根据当次 diagnose 与实测机械空间显式填写。stop 与独立断电急停的操作顺序见 [SD 操作说明](docs/SD启动与项目迭代操作说明.md)。板端运动不由构建脚本执行。

## 核心目录

| 目录 | 内容 |
| --- | --- |
| [src/pl/rtl/](src/pl/rtl/rtcs_top.sv) | AXI 寄存器、G2 六轴控制器、描述符检查、舵机协议与实际顶层 |
| [src/ps/linux/apps/](src/ps/linux/apps/rtcs_pl_g2_six.c) | G1、G2 单轴、G2 六轴 UIO CLI |
| [src/vision/](src/vision/) | cube/cylinder 多目标像素检测、USB Camera 与离线推理 |
| [config/](config/g2_measured_limits.toml) | 安装状态实测限位和参考位置 |
| [sim/](sim/README.md) | RTL、CLI mock、完整离线回归 |
| [scripts/](scripts/build_vivado.ps1) | Vivado、XSA 导入和 PetaLinux SD 构建 |
| [artifacts/hw/](artifacts/hw/rtcs_system.xsa) 与 [artifacts/sd/](artifacts/sd/SHA256SUMS) | ABI 0E XSA、bitstream、SD 三件套及哈希；旧 ABI 见归档 |
| [docs/](docs/0.1hardware_bringup.md) | 阶段 G0–G6、双轨制门禁、冲刺日程与每日任务卡 |
| [artifacts/reports/](artifacts/reports/competition-plan-material-assessment-20261012.md) | 竞赛计划与素材评估、交接提示词 |
| [artifacts/archive/](artifacts/archive/) | 旧 ABI 的 bit/XSA/SD 快照与操作记录；被取代的旧说明文档已清理，需要时从 git 历史取回 |

当前构建使用 Vivado 2023.2 与 PetaLinux 2023.2。默认构建不导出舵机 IO；实际 TTL 镜像须用 Vivado 脚本的 Build/Ttl 选项，并保留独立舵机电源与物理禁发。G3 的轨迹引擎、FIFO 与硬件 IRQ 仍未实现（PS 侧软状态机承担任务编排）；100 次静态抓放与 P99 统计属归档轨，不是运动前置条件。

## 视觉模块

`src/vision/` 提供 YOLO A 与实验性 OpenCV 几何检测入口，类别固定为 `0=cube`、`1=cylinder`，支持一帧输出多个目标的类别、置信度、原图检测框和像素中心。正式权重位于 `models/vision/`；视觉子模块的 AGPL-3.0 范围、第三方署名和复现步骤见 [视觉模块文档](docs/vision/README.md)，该范围不自动重许可独立的 FPGA/控制模块。

当前视觉结果不是毫米坐标或 Robot Base 坐标，也不提供 `yaw`；固定 Camera、真实 Homography 和最终传送带场景均尚未验收。视觉模块不会直接下发机械臂动作。
