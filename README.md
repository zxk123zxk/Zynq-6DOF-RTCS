# Zynq 六轴机械臂视觉引导抓取系统

面向流水线**异常品剔除工位**的桌面分拣单元：单目相机 + Zynq-7020 直驱 6 只 HX-30HM 总线舵机，
按异常品密度切换两种模式——带面静止时**批次拣选**，连续运行时**预测拦截**。

参赛编号 49824 · 2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新赛道 · AMD 自主选题（初级组）。

| 实测指标 | 数值 | 条件 |
| --- | --- | --- |
| 批次拣选成功率 | **13/13** | 40 mm 方块，带面静止，单轮 P50 7.84 s |
| 连续抓取成功率 | **15/16 = 93.8%** | 带速 60.4–66.7 mm/s，抓取段 P50 4.59 s、完整一轮 8.6 s |
| 落点偏差 | 0.1–1.2 mm | 预测落点 vs 实际咬合位置 |
| 臂到位抖动 | 4–19 ms | 折合 0.25–1.2 mm |
| PL 资源 | LUT 12.69%、FF 10.84%、BRAM 0 | XC7Z020，Vivado 2023.2 impl |
| 时序 | 100 MHz 全约束满足 | `All user specified timing constraints are met.` |

全部指标的口径、测试次数与证据文件见 [`metrics/`](metrics/README.md)。

## 目录对照（AMD 选题指南 3.3.5.4 推荐结构 → 本仓库）

推荐结构非强制，采用其他组织方式的队伍须给出对照。本仓库的对应关系：

| 推荐目录 | 本仓库 | 说明 |
| --- | --- | --- |
| `README.md` | `README.md` | 本文件 |
| `src/` | `src/` | `pl/`（SystemVerilog RTL + XDC + Vivado TCL）、`ps/`（PetaLinux app + Linux CLI）、`vision/`（检测与平面映射） |
| `sim/` | `sim/` | Verilator/Icarus 测试台与离线回归 `sim/run_regression_wsl.sh` |
| `build/` | `build.tcl` + `artifacts/reports/` | 构建入口在根目录（与报告附录 A 的命令一致），综合/实现报告在 `artifacts/reports/` |
| `board/` | `artifacts/hw/`、`artifacts/sd/`、`artifacts/sd_payload/` | `.bit` + `.xsa`、SD 三件套、板端运行载荷 |
| `data/` | `config/`、`evidence/`、`metrics/`、`models/` | 标定与示教表、逐次原始记录、指标汇总、权重 |
| `skill/` | `skill/` | 两个技能包，见 `skill/README.md` |
| `report/` | `docs/` | `report-1031.tex`/`.pdf`、`engineering-notes.md`、`llm-collaboration.md`、插图与厂商资料 |

仓库内目录名与文件名均为纯英文小写；报告插图已统一为 `flow-overview.png`、
`hardware-wiring.png`、`buslinker-pcb.png` 等英文名，`report-1031.tex` 内的引用同步更新。
唯一的中文名文件 `docs/镜像文件启动.md`（旧镜像的历史笔记，不参与当前流程）留在仓库里，
但**不随提交包分发**——提交包由 `scripts/package_submission.sh` 生成时自动剔除，符合赛题 3.3.5.4。

## 快速复现

1. **硬件**：AX7Z020 上电；6 只 HX-30HM 并联接独立 5–14 V 电源与单线总线，共地；
   相机固定在带面正上方，上位机用 USB-UART（115200 8N1）连板卡。
2. **构建**：`vivado -mode batch -source build.tcl` → `artifacts/hw/rtcs_system.bit` + `.xsa`
   （默认带 TTL 端口；加 `-tclargs base` 只做 BD/RTL 验证，不导出舵机 IO）。
   随后按 `src/ps/petalinux/` 的脚本由 XSA 生成 `BOOT.BIN` / `image.ub`。
3. **上板**：SD 卡放 `BOOT.BIN` + `image.ub` + 运行载荷；登录后把载荷拷到 `~/rtcs`
   （该目录在 RAM，断电即丢）。载荷由 `bash scripts/stage_sd_payload.sh` 从正本生成，
   5 个 `.py` → `~/rtcs/scripts/`，4 个配置 → `~/rtcs/config/`。
4. **标定与示教**：`belt_calibration_dynamic.py` 自动找带面四角存 `calibration.json`；
   `teach_add_point.py` 逐点回读五轴位置建 6 点示教表。**关节值只能取自现场 `diagnose` 回读，
   不得按几何比例推导。**
5. **运行**：板端起 `static_grasp_server.py`；上位机二选一
   —— `capture_agent.py --serial COM8 --class-name cube`（批次拣选）
   —— `g5_dynamic_trigger.py --serial COM8 --loop`（连续抓取）。
   每轮输出 `grip=contact|empty`、`gripper_position`、`cycle_ms`。

完整步骤见 `docs/report-1031.pdf` 附录 A；接口、参数与故障表见
[`docs/engineering-notes.md`](docs/engineering-notes.md)。

## 两种模式的差别

共用同一条链路（视觉 → 一对毫米坐标 → PS 七步状态机 → PL 总线帧 → 舵机），差别只在决策层：

- **批次拣选**：带面静止，上位机取点后逐件下发，"看准了再动"。
- **连续抓取**：每帧估带速，`x_int = x + v×(advance+move+margin)` 现算拦截点，
  按预测时刻推进、**到位即闭爪**，实测臂到位抖动 ≤19 ms。

## 代码地图

| 位置 | 内容 |
| --- | --- |
| `src/pl/rtl/` | `hx30hm_g1_engine.sv`（协议时序）、`g2_six_axis_controller.sv`（六轴同步/限位/deadline）、`g2_descriptor_guard.sv`（帧前硬校验）、`safety_monitor.sv`、`axi_lite_regs.sv` + `rtcs_pkg.sv`（ABI `0x5254000E`） |
| `src/ps/linux/apps/` | `rtcs-pl-g2`、`rtcs-pl-g2-six` 用户态 CLI（UIO mmap） |
| `src/vision/` | 检测与平面单应映射，输出毫米坐标 |
| `scripts/` | 板端 `static_grasp_server.py`、`g3_station_runner.py`、示教/标定/调速工具、载荷打包 |
| `vision_v11/…/scripts/` | 上位机 `capture_agent.py`、`g5_dynamic_trigger.py`、`grasp_point.py`、`belt_calibration_dynamic.py` |
| `skill/` | 技能包：Zynq AXI 外设 bring-up、PetaLinux 镜像构建 |

## 验证与证据

- 仿真：`bash sim/run_regression_wsl.sh`（Verilator 5.008）→ `RTCS_WSL_REGRESSION_PASS`。
- 综合与实现：`artifacts/reports/utilization.rpt`、`timing_summary.rpt`。
- 板级：`evidence/` 下逐次记录（静态 13 次、动态 17 次），与报告 3.3 节逐条对应。

## 许可

本队自研部分（RTL、PS 侧程序、上位机与板端脚本、文档）采用 [MIT](LICENSE)。
第三方依赖各自遵循其许可：Ultralytics YOLO11 与由其训练得到的权重为 AGPL-3.0，
OpenCV 为 Apache-2.0，PetaLinux 与 Vivado 产物遵循 AMD 相应条款；
`docs/resource_file/` 下的厂商手册版权归原厂，仅作工程参考随附。
