# Repository and reference guidance

## Active project source of truth

Use these paths for the AX7020/XC7Z020 implementation:

- `src/pl/rtl/`: `rtcs_top.sv` integration; `axi_lite_regs.sv` control-plane register bank; `trajectory_engine.sv`, `servo_bus_master.sv`, and `safety_monitor.sv` deterministic control boundaries; `rtcs_pkg.sv` shared RTL definitions.
- `src/ps/linux/`: UIO/MMIO application, shared register definitions, and CMake build.
- `docs/engineering-notes.md`: 当前唯一的工程参考（硬件基线、实测限位、ABI/寄存器、串口契约、七步计划、动态参数、故障表）。G0–G6 各阶段记录已于 2026-11-03 合并进此文件，过程原文从 git 历史取。
- `docs/report-1031.tex` / `.pdf`: 技术文档正本（冻结，只由文档负责人改）。
- `metrics/`: 指标汇总表与口径，每行都指向 `evidence/` 下的原始记录。
- `config/`: measured calibration and arm/bus data only; `arm_calibration.template.toml` is a template, not verified physical data.
- `sim/`: RTL/protocol testbench and result material. `scripts/`: reproducible inspection and verification helpers.
- `src/pl/vivado/create_project.tcl` and `src/pl/xdc/ax7020_template.xdc`: build and board-constraint inputs. Pin assignments remain placeholders until verified against the exact AX7020 schematic.
- `src/pl/rtl/rtcs_pkg.sv` 与 `src/ps/linux/include/rtcs_registers.hpp`: PS/PL 寄存器契约；可观察接口变化时必须同步更新二者与相应阶段文件。

## 双轨制（dual-track gates）

`CLAUDE.md` 与本节定义两条轨道，处理本仓库任何门禁、排期或评审时都要套用：

- **竞赛轨（快）**：每周产出可演示增量，**只保留红线门禁**，流程门禁全部关闭。
- **归档轨（慢）**：满足文档、答辩与可复查性，**红线 + 全部流程门禁**。

**红线门禁**（任何轨道都不得绕过）：舵机独立供电；物理禁发跳线；PL 编译期目标/速度/截止时间/总线互斥检查；独立于 Linux/PS/PL 的硬件急停；只采用实测标定值；单次提交最多一帧；不得自动重试已报 ERR 的运动命令。

**流程门禁**（仅归档轨）：`config/g3_station_plan.template.json` 的逐步 `operator_confirmed` 与证据引用（由 `scripts/g3_offline_plan.py` 校验）；每命令完整原始输出归档；"位置反馈不能单独证明抓取成功"判定链；100 次循环全量记录；P99 统计；长跑统计。

**硬规则：任何流程性门禁不得阻塞竞赛轨的运动路径。** 只产生"证据要求"而不阻止危险动作的检查，在竞赛轨中不得作为运动前置条件。反之，**红线门禁绝不因赶工期而放宽**——工期压力只能通过削减功能范围缓解。

**已确认的硬件基线（2026-10-12）**：板端 ABI `0x5254000E` 已实测；**ID 1–5 为关节、ID 6 为夹爪**；相机为**中奥维柯 3 mm / 90° 无畸变 UVC + CPL 偏振片**（2026-10-17 替换原幻尔 120° 广角，实测 1280×720，无深度），因此本工程**不使用点云或深度学习抓取检测**，视觉走"单目 2D + 平面单应映射"。

## Material_Library: permitted references, not dependencies

`Material_Library/mycpu--/` is an independent RISC-V SoC with an RT-Thread Nano port. It can inform self-contained RTL organization, simulation/testbench patterns, FPGA build structure, MMIO trace/debugging, and RTOS-port investigation. It does not define the AX7020 robot architecture, its AXI interface, or its servo protocol.

Start with these paths only when relevant:

- `Material_Library/mycpu--/AGENTS.md` for local constraints and current validation context.
- `Material_Library/mycpu--/rtl/`, `tb/`, `tests/`, `tools/`, and `docs/` for RTL, verification, utilities, and RT-Thread-related evidence.

`Material_Library/kr260_robotic_arm-main/` is a complete KR260/ROS2 project with a USB-serial/PWM six-axis arm. It can inform high-level camera, color-recognition, ROS2-node, and demo-workflow ideas. Its board, Ubuntu/ROS stack, PWM actuator interface, and USB serial transport are incompatible with this AX7020/HX-30HM half-duplex servo-bus design.

Start with these paths only when relevant:

- `Material_Library/kr260_robotic_arm-main/README.md` for the project boundary and operator workflow.
- `Material_Library/kr260_robotic_arm-main/opencv_ros2/` and `vision_opencv/` for vision/ROS2 examples.
- `Material_Library/kr260_robotic_arm-main/如何启动KR260.md` and `如何在KR260上运行ROS.md` for KR260-specific environment procedures.

Before adapting any reference behavior, explain the platform/interface difference, reimplement the necessary logic in the active project's conventions, and record provenance/license questions. Never claim a reference-project test validates this controller.
