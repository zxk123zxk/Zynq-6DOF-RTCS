# 指标汇总

`metrics.csv` 是机读版本（7 列：metric / category / value / unit / condition / evidence / reproduce），
本文件是同一份数据的人读版本与口径说明。**报告里有、这里没有的数字不许出现；这里有的数字必须能点到证据文件。**

## 测试环境（所有指标共用）

| 项 | 取值 |
| --- | --- |
| 器件 | XC7Z020CLG400-2（ALINX AX7Z020），PS 双核 A9 @667 MHz，PL 100 MHz |
| 软件 | Vivado / PetaLinux 2023.2，板端 Python 3.10；上位机 Python 3.11 + Ultralytics 8.4 + OpenCV 4.10（CPU） |
| 硬件 ABI | `0x5254000E` |
| 执行器 | 6× HX-30HM，1 Mbps 8N1 半双工；ID6 夹爪 |
| 视觉 | 1280×720 UVC，YOLO11n，`conf=0.25`、`imgsz=640`，CPU 推理约 22 FPS |
| 工件 | 40 mm 3D 打印方块（异常件）；圆柱为合格件，不抓 |

## 核心指标

| 指标 | 数值 | 次数 / 时长 | 证据 |
| --- | --- | --- | --- |
| 静态抓取成功率 | **13/13 = 100%** | 13 次连续触发，2026-10-26 | `evidence/g3-static-closedloop-20261026.md` |
| 动态抓取成功率 | **15/16 = 93.8%** | 17 次触发（1 次未越线不计入），2026-10-30 16:40–16:48 | `evidence/g5-dynamic-20261030.md` |
| 静态单轮周期 | P50 7.84 s / P95 9.42 s / max 10.96 s | 13 次 | 同上 |
| 动态单轮周期 | P50 4.589 s / P95 4.788 s / max 5.458 s | 15 次命中 | 同上 |
| 定位重复性 | ±0.15 mm | 同点 3 次 | `evidence/g3-static-openloop-20261025.md` |
| 落点偏差（动态） | 0.1–1.2 mm | 15 次 | `evidence/g5-dynamic-20261030.md` |
| 臂到位抖动 | 4–19 ms（折合 0.25–1.2 mm @63 mm/s） | 15 次 | 同上 |
| 可抓取区间 | 295–420 mm | 六点示教表 | `config/grasp_teaching_table.json` |

## 资源与时序

| 指标 | 数值 | 证据 |
| --- | --- | --- |
| LUT | 6 751 / 53 200 = **12.69%** | `artifacts/reports/utilization.rpt` |
| FF | 11 537 / 106 400 = **10.84%** | 同上 |
| DSP | 2 / 220 = 0.91% | 同上 |
| BRAM | 0 / 140 | 同上 |
| 时序 | 100 MHz，`All user specified timing constraints are met.` | `artifacts/reports/timing_summary.rpt` |

## 统计口径（答辩会被追问的三条）

1. **动态成功率的分母**是"越线并触发"的 16 次；1 次工件未到触发线、由人工结束，不计入。失败的那 1 次
   是低速段（v 估成 16.4 mm/s、$T_{flight}$ 被算成 13.95 s）只咬到边角，属已知失效形态。
2. **两种模式的周期不可直接比较**：静态含一次从复位位的长行程 approach，动态从待命位起算。
3. **成功率来自单批次**（同一次会话），未做跨日期、跨带速档位的重复；对外只引用为"本批次实测"，
   不当作长期指标。
