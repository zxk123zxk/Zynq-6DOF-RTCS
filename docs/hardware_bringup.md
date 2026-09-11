# Hardware bring-up checklist（硬件上板检查清单）

This checklist is a required gate, not optional documentation. Record measurement files under `data/` when the format is decided; do not commit personal or unverified raw captures by default.

（中文：此检查表是必经门禁，不是可选文档。确定数据格式后将测量文件记录到 `data/`；默认不要提交个人或未经验证的原始采集数据。）

## G0: board and power（板卡与供电）

- [ ] Confirm AX7020 PCB revision and exact XC7Z020 speed/package from board markings/schematic.（从板卡标记/原理图确认 AX7020 PCB 版本及 XC7Z020 的准确速度等级/封装。）
- [ ] Confirm PL bank voltage and the UART transceiver's compatible logic levels.（确认 PL Bank 电压与 UART 收发器兼容的逻辑电平。）
- [ ] Use a dedicated, measured servo supply. Never power six servos from a Zynq GPIO rail.（使用独立且测量过的舵机电源；绝不能从 Zynq GPIO 电源轨给六个舵机供电。）
- [ ] Confirm common ground and measure idle bus voltage.（确认共地并测量总线空闲电压。）
- [ ] Confirm E-stop physically removes/blocks actuation independently of software.（确认急停可脱离软件、从物理上切断/阻止执行动作。）

## G1: one servo protocol bench test（单舵机协议台架测试）

- [ ] Isolate one servo; record its ID and powered idle current.（隔离一个舵机，记录其 ID 与上电空闲电流。）
- [ ] Capture a 1 Mbps 8N1 PING waveform and validate checksum.（采集 1 Mbps、8N1 PING 波形并验证校验和。）
- [ ] Issue one `READ` of position at address `0x38`, length 2; record received bytes and response timeout.（对地址 `0x38`、长度 2 发出一次位置 `READ`，记录接收字节与应答超时。）
- [ ] Keep `servo_tx_en=0` in FPGA until PHY direction control and high-impedance release timing are demonstrated.（在证明 PHY 方向控制及高阻释放时序前，FPGA 中始终保持 `servo_tx_en=0`。）
- [ ] Test malformed frame, checksum error, no-response timeout and cable disconnect.（测试畸形帧、校验和错误、无应答超时和断线。）

## G2: arm calibration（机械臂标定）

- [ ] Build a six-axis ID table including mechanical joint, bus ID, zero count, direction, safe min/max, and home pose.（建立六轴 ID 表，包含机械关节、总线 ID、零位计数、方向、安全最小/最大值和回零姿态。）
- [ ] Confirm target-position write base `0x2A` and six-byte payload (position, time, speed) against an actual HX-30HM response.（以真实 HX-30HM 应答确认目标位置写基址 `0x2A` 和六字节载荷：位置、时间、速度。）
- [ ] Test `SYNC WRITE` only at low speed and clear workspace.（只能在低速且工作空间清空时测试 `SYNC WRITE`。）
- [ ] Treat `SYNC READ` as unsupported until all six replies are ordered and checksum-valid on the real bus.（在真实总线上六个应答均有序且校验和有效之前，视 `SYNC READ` 为不支持。）

## G3: integrated safety tests（集成安全测试）

- [ ] Verify PL reset, AXI software stop, watchdog timeout and hardware E-stop all prevent transmit.（验证 PL 复位、AXI 软件停止、看门狗超时和硬件急停都能阻止发送。）
- [ ] Verify command deadline-miss, joint limit, checksum failure and feedback timeout are logged and observable to PS.（验证命令超期、关节限位、校验失败和反馈超时均被记录且 PS 可观察。）
- [ ] Run 100 static cycles, recording success/failure, maximum position error and human interventions.（运行 100 个静态循环，记录成败、最大位置误差和人工干预。）
