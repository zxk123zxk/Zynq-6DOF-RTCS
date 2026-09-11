# Architecture and stage boundaries（架构与阶段边界）

## Fixed partition（固定职责划分）

| Layer（层级） | Owns（负责） | Must not own（不应负责） |
| --- | --- | --- |
| PS / Linux（处理系统/Linux） | camera, classification, calibration, coordinate conversion, FK/IK, task FSM, target prediction, deadline generation, logging（相机、分类、标定、坐标转换、正逆运动学、任务状态机、目标预测、截止时间生成、日志） | UART bit timing, servo bus arbitration, emergency timing（UART 位时序、舵机总线仲裁、紧急时序） |
| AXI contract（AXI 契约） | command descriptor, status, counters, IRQ acknowledgement（命令描述符、状态、计数器、中断确认） | image buffers or high-rate feedback streams in phase 1（第 1 阶段的图像缓冲或高速反馈流） |
| PL / RTL（可编程逻辑/RTL） | command buffering, trajectory timing, multi-axis issue, UART protocol, response parser, watchdog, limits and E-stop（命令缓冲、轨迹计时、多轴下发、UART 协议、应答解析、看门狗、限位与急停） | model inference or high-level task policy（模型推理或高层任务策略） |
| Servo（舵机） | internal motor current/position loop（内部电流/位置闭环） | global task scheduling（全局任务调度） |

The first version intentionally uses AXI4-Lite for commands and status. If feedback bandwidth later proves insufficient, add AXI DMA only after measuring the limitation; do not introduce it speculatively.

（中文：首版特意使用 AXI4-Lite 传递命令和状态。若后续实测证明反馈带宽不足，再加入 AXI DMA；不要在没有证据时提前引入。）

## PL data path（PL 数据通路）

```text
AXI4-Lite -> register bank -> command FIFO -> trajectory engine
                                      |             |
                                      v             v
                               irq/counters <- scheduler -> HX packet engine -> half-duplex PHY
                                                    ^                              |
                                                    +-- feedback parser <----------+
                                      safety monitor / watchdog / E-stop
```

The current RTL implements the register-bank boundary only. `trajectory_engine`, `servo_bus_master` and `safety_monitor` have named, documented interfaces but are deliberately not connected to a live bus yet.

（中文：当前 RTL 仅实现寄存器组边界。`trajectory_engine`、`servo_bus_master` 和 `safety_monitor` 虽已有命名且已文档化的接口，但刻意尚未接入真实总线。）

## Command lifecycle（命令生命周期）

1. PS validates IK result, calibrated joint limits and a monotonic deadline.（PS 校验逆运动学结果、已标定的关节限位和单调递增的截止时间。）
2. PS writes all six target registers, profile registers and deadline.（PS 写入全部六个目标寄存器、速度/加速度寄存器和截止时间。）
3. PS writes `COMMAND` last with `ENQUEUE` set; this is the commit point.（PS 最后写入置位 `ENQUEUE` 的 `COMMAND`；这一步才正式提交命令。）
4. PL atomically snapshots the descriptor, validates it, queues it and returns a sequence number.（PL 原子地快照、校验并入队该描述符，然后返回序列号。）
5. The scheduler emits `SYNC WRITE` packets at the planned cadence; feedback is checked against timeout/error policy.（调度器按计划周期发送 `SYNC WRITE` 包，并按超时/错误策略检查反馈。）
6. PL raises IRQ for completion, deadline miss, servo fault or safety fault. PS reads `IRQ_STATUS`, records the outcome, then acknowledges it.（完成、超期、舵机故障或安全故障时 PL 触发中断；PS 读取、记录并确认 `IRQ_STATUS`。）

This lifecycle prevents a partially written target vector from reaching a servo.

（中文：这一生命周期可防止只写了一部分的目标向量被发送给舵机。）

## Non-negotiable safety invariants（不可妥协的安全不变量）

- Reset, watchdog expiry, hardware E-stop and illegal command all force bus transmit disable.（复位、看门狗到期、硬件急停和非法命令都会强制禁用总线发送。）
- Every limit in `config/` comes from a measured/calibrated arm; no guessed mechanical limits.（`config/` 的每一项限位均须来自实测/标定的机械臂；禁止猜测机械限位。）
- Broadcast PING is prohibited because the HX protocol permits multiple replies on the same bus.（禁止广播 PING，因为 HX 协议允许多个设备在同一总线上回复。）
- `SYNC READ` is optional until demonstrated on all six physical servos; sequential `READ` is the baseline feedback path.（在六个真实舵机上证明前，同步读仅为可选项；顺序 `READ` 才是基线反馈路径。）

## Stage gates（阶段门禁）

| Gate（门禁） | Required evidence（所需证据） | Enables（允许进入） |
| --- | --- | --- |
| G0 | AX7020 board/pin/supply verification（板卡、引脚、电源核验） | PS7 + AXI integration（PS7 与 AXI 集成） |
| G1 | logic-analyzer waveform for one servo PING/READ（单舵机 PING/READ 逻辑分析仪波形） | TX enable for bench test（台架测试发送使能） |
| G2 | six ID/zero/limit records and isolated motion test（六轴 ID/零位/限位记录及隔离运动测试） | `SYNC WRITE`（同步写） |
| G3 | RTL simulation + 100 static pick/place cycles（RTL 仿真加 100 次静态抓放循环） | trajectory and feedback closed loop（轨迹与反馈闭环） |
| G4 | moving-belt trial, deadline and P99-jitter data（运动皮带试验、截止时间和 P99 抖动数据） | final demo（最终演示） |
