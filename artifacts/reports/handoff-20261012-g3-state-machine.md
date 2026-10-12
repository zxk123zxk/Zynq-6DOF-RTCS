# 交接提示词：G3 六步状态机与自动循环（2026-10-12）

> 用法：把下面 `---` 之间的整段复制到新对话作为第一条消息。

---

你在 `D:/3.Electronic_Information/2026.9-ES_Competition-FPGA-AMD/Zynq-6DOF-RTCS` 这个仓库工作。这是一个 AX7020（XC7Z020）Zynq-7020 工程：**PS（Linux/UIO）负责视觉、标定、任务编排，PL（RTL）负责时序关键的六轴 HX-30HM 总线控制**。

## 背景：已经确定的硬件事实（不要再去验证或质疑）

- 板端已刷入并实测 ABI **`0x5254000E`**，`physical_tx=ENABLED`。源码、bitstream、XSA、SD 三件套与此一致。
- **ID 1–5 是关节舵机，ID 6 是夹爪舵机**（用户 2026-10-12 确认）。夹爪与关节共用同一条六轴广播命令，**不要为夹爪另建旁路**。
- **ID 5 的旧窄内部角度窗口（曾为 [1926, 2049]）已由官方软件重新校准解除**：2026-10-12 单轴 `--target 1500` 由 1907 运动到 1510，`fault=0 in_band=1 unicast_ack=1`，20 样本 1008 ms。**ID 5 已可正常使用，不要再把它当故障源排查。**
- 相机是 **幻尔 30 万像素 / 120° 广角 USB 免驱摄像头（无深度图）**，队友已在 PC 上装好 OpenCV 并可取流。所以本工程**不使用点云、不使用 GraspNet/Graspness 等深度学习抓取检测**；视觉走"单目 2D + 平面单应映射 + 畸变校正"。

## 必读（按此顺序，只读这四份就够）

1. `docs/0.1hardware_bringup.md` —— 阶段门禁总规划，**重点是"双轨制"**。
2. `docs/3.G3-static-closed-loop.md` —— 本对话要推进的阶段。
3. `skill/zynq-6dof-rtcs/SKILL.md` 与 `skill/zynq-6dof-rtcs/references/repository-guidance.md` —— 工程边界与流程约定。
4. `src/ps/linux/apps/rtcs_pl_g2_six.c` 与 `src/pl/rtl/rtcs_pkg.sv` —— 寄存器契约与 CLI 现状。

## 本对话要完成的任务

**目标：在 PS 侧实现 G3 的"六步任务状态机 + 连续自动循环"，让一次授权后能连续跑 `standby → approach → grasp → lift → place → exit`，失败即停并保留日志。**

具体交付：

1. **新增 PS 侧状态机入口。** 在 `src/ps/linux/apps/` 下新增一个应用（或在 `rtcs_pl_g2_six.c` 中新增子命令），提供：
   - 从配置文件读取六步 × 六轴的实测目标（`config/` 下新增一个实测工位表；不要预设姿态）；
   - 逐步下发六轴命令，每步检查 `fault` 与各轴到位结果；
   - **任一步失败立即停止当次循环、保存该步完整原始输出、不自动重试**；
   - 支持 `--cycles N` 连续跑 N 次，每轮记录：成功/失败、六轴最大目标误差、循环耗时；
   - 结束时输出一个可解析的汇总行（例如 `RTCS_G3_CYCLE_DONE ok=.. fail=.. cycles=..`）。
2. **新增离线守护脚本。** 在 `sim/` 下加一个 mock UIO 的守护脚本（照 `sim/run_pl_g2_six_cli_guard.sh` 的写法），断言：非法工位表被拒、失败时确实停止且不重发、`--cycles` 计数正确、汇总行格式正确。把它加入 `sim/run_regression_wsl.sh`。
3. **同步文档。** 更新 `docs/3.G3-static-closed-loop.md` 与 `sim/README.md` 记录新入口；若新增/改动寄存器语义，必须同时改 `src/pl/rtl/rtcs_pkg.sv` 与 `src/ps/linux/include/rtcs_registers.hpp` 并升 ABI。
4. **必须跑通** `bash sim/run_regression_wsl.sh`，最终输出 `RTCS_WSL_REGRESSION_PASS`。

## 明确跳过（做了就是浪费工期）

- ❌ 不训练任何深度学习模型；不引入 ROS / MoveIt / Gazebo。
- ❌ 不做解析逆运动学（5 关节 + 平面抓取，示教表足够）；本任务**只做状态机与循环**。
- ❌ **不要填 `config/g3_station_plan.json` / `g3_observation_log.json`，也不要为通过 `scripts/g3_offline_plan.py` 而努力** —— 那是"归档轨"，不是运动前置条件。
- ❌ 不重综合 bitstream、不重建 PetaLinux 镜像（本环境跑不了 Vivado/PetaLinux，由操作者在 WSL 与本机执行）。
- ❌ 不改 `trajectory_engine.sv` / `servo_bus_master.sv` / `safety_monitor.sv`；不新增 FIFO、硬件 IRQ、DMA、HLS。
- ❌ 不删除 `Material_Library/` 或 `.workbuddy/`。

## 纪律（务必遵守）

- **双轨制是最高优先级约定**：竞赛轨只保留红线门禁（独立供电、物理禁发、PL 限位/速度/截止时间、独立硬件急停、实测标定、单帧提交、不自动重试）。**任何流程性门禁不得阻塞竞赛轨的运动路径。** 不要给新代码加"每步必须人工确认才能继续"的硬门。
- **回归必须 PASS 才能交付。** 未跑或未通过时必须如实说明，不得声称通过。
- **源码与镜像必须一致**；改了 RTL 就要说明需要重综合，改了 CLI 就要说明需要重建 PetaLinux 应用包。
- **不谎报**：没有实测的数据不得写成实测；板端运动不由你执行。
- **本机 Bash 有文本级黑名单**：命令行文本中不得出现那些 Windows shell 相关字面词（连注释、`grep` 模式、`echo` 标签都要避开），否则命令会被策略拒绝。
- 报告格式：按 `skill/zynq-6dof-rtcs/SKILL.md` 的要求，用**仓库相对路径**（至少两级父目录）列出改动文件，并给出验证证据与剩余风险。

---

## 附：交接元信息（无需复制到新对话）

- 基线：ABI `0x5254000E`；`artifacts/sd/` 与源码同步。
- 本提示词前置：`docs/0.1hardware_bringup.md`（双轨制 + G0–G6）、`docs/7.sprint-plan-daily-tasks.md`（W1–W2 的 P0 任务）。
- 相关历史交接：`artifacts/reports/handoff-prompt-id5-archive-and-g3g4-20261010.md`（ID 5 时代，已被本次取代）。
