# Eight-week execution plan（八周执行计划）

The scope lock is a deliverable: later weeks refine measurement and demonstration rather than replace the architecture.

（中文：范围冻结本身也是交付物；后续周次只完善测量与演示，而不推翻架构。）

| Week（周） | Deliverable（交付物） | Owner（负责人） | Acceptance evidence（验收证据） |
| --- | --- | --- | --- |
| 1 | G0 board/bus evidence, PS7/AXI project, one-servo protocol capture（G0 板卡/总线证据、PS7/AXI 工程、单舵机协议抓取） | Chen + Yuan + system | ID/electrical table, waveform, bitstream build log（ID/电气表、波形、比特流构建日志） |
| 2 | PING/READ RTL simulation and one-servo PL test; UIO register round trip（PING/READ RTL 仿真、单舵机 PL 测试；UIO 寄存器往返测试） | Yuan + system | packet tests, AXI test, measured response log（数据包测试、AXI 测试、实测应答日志） |
| 3 | six-servo `SYNC WRITE`, calibration table, safety gates（六舵机同步写、标定表、安全门禁） | Yuan + Chen | low-speed home/pose demo and fault tests（低速回零/姿态演示和故障测试） |
| 4 | profile baseline, static pick/place, Linux-only baseline（轨迹基线、静态抓放、仅 Linux 基线） | system + Yuan | 100-cycle table, latency and jitter measurements（100 循环表、延迟和抖动测量） |
| 5 | camera calibration, OK/NG classifier, fixed-position correction（相机标定、良品/不良品分类、固定位置校正） | system + Chen | repeatable coordinate and classification metrics（可重复坐标与分类指标） |
| 6 | conveyor timing/target prediction and dynamic catch（传送带计时/目标预测与动态抓取） | system + Chen | deadline-hit rate and end-to-end latency（截止时间命中率和端到端延迟） |
| 7 | stress, failure injection, benchmark scripts and report data（压力、故障注入、基准脚本和报告数据） | all（全体） | long-run record, P99 jitter, resources/timing（长时记录、P99 抖动、资源/时序） |
| 8 | scope freeze, demo script, reproducibility clean-room run, poster/report（范围冻结、演示脚本、可复现净环境运行、海报/报告） | all（全体） | tagged release and rehearsal（带标签的发布版本和演练） |

The MVP ends at week 4: safe six-axis static pick/place with measured PS–PL benefit versus a Linux-only control baseline. Dynamic correction, S-curve and SYNC READ are enhancements only after that gate.

（中文：最小可行产品在第 4 周完成：安全的六轴静态抓放，并量化 PS–PL 相对纯 Linux 控制基线的收益。动态校正、S 曲线和同步读只可在此门禁通过后作为增强项。）
