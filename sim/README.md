# Verification plan（验证计划）

Add simulation artifacts in phases; keep testbenches independent from board-specific pin constraints.（分阶段加入仿真产物；测试平台必须独立于板级特定的引脚约束。）

1. `tb_axi_lite_regs`: reset, read ID/version, partial-write behavior, all six target registers, read/write response handshake.（复位、读取 ID/版本、部分写行为、全部六个目标寄存器及读/写应答握手。）
2. `tb_hx30hm_protocol`: HX-30HM PING/READ and the ABI 08 torque+position / torque-off checksum golden vectors, including nonzero raw time. It validates only packet arithmetic, never physical output.（校验报文运算及非零原始时间字段，不验证物理输出。）
3. `tb_half_duplex_phy`: 1 Mbps 8N1 timing, direction turnaround and no-drive-after-E-stop assertions.（1 Mbps、8N1 时序、收发方向切换，以及急停后不得驱动总线的断言。）
4. `tb_motion_safety`: simultaneous six-axis descriptor commit, deadline miss, watchdog, limit and feedback-timeout behavior.（同时提交六轴描述符、截止超期、看门狗、限位和反馈超时行为。）

## AXI4-Lite register regression（AXI4-Lite 寄存器回归）

Run the following command from the repository root with Icarus Verilog installed. The G1 and AXI runners use `iverilog -g2012` and `vvp`; their build products are written below ignored `build/sim/`.

```powershell
powershell -ExecutionPolicy Bypass -File sim/run_axi_lite_regs.ps1
powershell -ExecutionPolicy Bypass -File sim/run_hx30hm_protocol.ps1
powershell -ExecutionPolicy Bypass -File sim/run_servo_rx_only.ps1
powershell -ExecutionPolicy Bypass -File sim/run_hx30hm_g1_engine.ps1
powershell -ExecutionPolicy Bypass -File sim/run_rtcs_g1_safe_top.ps1
powershell -ExecutionPolicy Bypass -File sim/run_rtcs_g1_ttl_top.ps1
powershell -ExecutionPolicy Bypass -File sim/run_g2_descriptor_guard.ps1
powershell -ExecutionPolicy Bypass -File sim/run_rtcs_g2_one_servo.ps1
```

`tb_axi_lite_regs.sv` verifies synchronous reset, read-only register reads, AW-first/W-first/same-cycle writes, held B/R responses, non-contiguous byte writes, and independent readback of all six target registers. A successful run ends with `TB_AXI_LITE_REGS_PASS`.

（中文：`tb_axi_lite_regs.sv` 覆盖同步复位、只读寄存器、AW 先到/W 先到/同周期写、保持的 B/R 应答、非连续字节写以及六轴目标寄存器独立读回；成功时输出 `TB_AXI_LITE_REGS_PASS`。）

Every test should be executable from a script in this directory and should state the simulator/version used. Do not claim a waveform-only pass as real servo validation.（每项测试均应能由本目录脚本执行并注明所用仿真器/版本；只有波形通过不能宣称已完成真实舵机验证。）

`sim/tb_hx30hm_g1_engine.sv` checks 1 Mbps PING/READ, the ABI 08
15-byte torque+position motion frame, the 8-byte torque-off frame, valid
replies, invalid ID, the removed position-only opcode, and missing-response
timeout without any servo connection.
`sim/tb_rtcs_g1_safe_top.sv` drives G1 commands through AXI and checks that
the no-TTL wrapper ignores them and keeps `servo_tx_en=0`, `servo_tx=1`.
This does not validate electrical levels or real servo replies.
`sim/tb_rtcs_g1_ttl_top.sv` checks default inhibit, physical TX activation
only after the separate strap is grounded, immediate TX release on inhibit,
transaction abort and no automatic resume. Real servo replies remain an
on-board test described in the SD guide.
`sim/tb_g2_descriptor_guard.sv` checks atomic six-axis capture and rejection
of uncalibrated, out-of-range, faulted, inhibited and expired descriptors.
The six-axis guard is not wired to the physical servo UART. In WSL, run
`bash sim/run_pl_g1_cli_abi.sh` to verify the Linux CLI rejects ABI 02 before
register writes and accepts ABI 08 for a read-only `probe`.

The connected G2 path is covered by `bash sim/run_g2_one_servo.sh` in WSL
(Verilator 5.008 with `--binary --timing`). The Windows Icarus runner remains
available, but the installed Icarus executable currently exits with access
violation `0xC0000005` during package compilation; the verified regression gate
is `bash sim/run_regression_wsl.sh`. The G2 test checks physical inhibit, ID/field-width/deadline
rejection, the G1-path whitelist (position-writing opcodes fault 13), an arbitrary
old EXPECT field and distant start position, atomic snapshot, the exact ABI 08
torque+position frame (`0x28=1` plus variable target/time/speed), repeated explicit
submissions, ±15 feedback boundary, delayed arrival as success, bounded observation
timeout without automatic retry, physical inhibit after launch, and torque release.
It never connects to a real servo. Inhibit truncates a frame on purpose, so the
testbench re-synchronises its byte observer before the next command.
`bash sim/run_pl_g2_cli_guard.sh` compiles the Linux CLI and uses mock UIO
mappings to confirm ABI/width checks and physical inhibit reject before `G2_CMD`,
while distinct targets and raw fields are packed correctly. It also checks the
CLI's independent final-error and delayed-arrival reporting.

For the current WSL toolchain, `bash sim/run_regression_wsl.sh` runs the AXI,
protocol, G1, six-axis offline guard, connected G2, and both CLI mock suites.
`bash sim/run_g3_offline_plan_guard.sh` additionally pins the G3 offline gate in
`scripts/g3_offline_plan.py`: the empty station template must be rejected, a plan
without `id5_fault_cleared_by_operator` must be rejected, an ID 5 target outside
the measured range must be rejected (which also proves `safe_min`/`safe_max` were
actually read, not skipped), a confirmed plan must pass `--step standby` and emit
only one `MANUAL_REVIEW_ONLY` command with `motion_executed=0`, and a post-standby
step must be rejected without `--log`. That checker needs `tomllib`, so the script
carries a strict fail-closed fallback for hosts that only ship Python 3.10.
The descriptor guard uses packed 32-bit axis arrays so Verilator 5.008 observes
post-initialization changes at the module port; ABI 09 also tests its connected
six-axis controller path.

# ABI 10 六轴离线验证

`sim/run_regression_wsl.sh` 另运行 `tb_g2_six_axis_controller` 和 `run_pl_g2_six_cli_guard.sh`。前者使用假总线应答覆盖：默认校准掩码为零时不发 WRITE、物理禁发、限位拒绝、六轴连续三轮反馈、第二次显式同步提交、5 秒窗口超时无重发、反馈错误对应 ID 和闭锁、读六轴后软件停止、两次现场 READ 后 50 count 标定及超过 50 count 拒绝。`tb_hx30hm_g1_engine` 逐字节核对完整 62 字节广播帧、每轴 `0x28=1`、目标/时间/速度字段和校验和，并验证广播完成不等待应答。CLI mock 验证无 `--execute`、未标定和过大步差均不写命令寄存器。仿真不替代安装后安全限位及断电急停的实物验收。

ABI 10 另验证标定 +20 仅前进 6 count 不能通过、目标 ±5 边界、fault 9 后仍可显式手动标定而 SYNC 仍闭锁、128 条日志容量与溢出拒绝、逐条反馈元数据和超时原因、ID 2–6 单轴帧，以及只读 `0x28` 的请求、应答 ID/长度/校验和/伺服错误。所有新运动仍仅由 G2 状态机发起；G1 操作码 3 和 8 继续拒绝。

ABI 11 新增 `tb_g2_board_limits`：使用实际六轴综合常量逐轴覆盖最小值、最大值及相邻越界值（ID 5 包括 0/4000），并检查速度原始字段 0/500/1500/1501、物理禁发和 ID 2 边界外标定不得发 WRITE。`tb_rtcs_g1_ttl_top` 在禁发时读回 `calibrated_mask=0x3f` 与每轴 min/max/参考位置/速度上限。

当前 ABI 14 的 `tb_g2_six_axis_controller` 验证六轴绝对命令先 WRITE、失败 READ 发生在发后且保留 WRITE 状态、六轴连续三轮有效到位，以及 stop/相对标定功能性发前 READ。`tb_rtcs_g2_one_servo` 验证单轴先 WRITE、正常 ACK 和三次发后有效到位反馈、目标已在误差带内的绝对命令，以及超时不自动重发。`tb_axi_lite_regs` 检查 0x100 以上寄存器与 ABI 地址不混叠。CLI mock 检查无起点时仍可按反馈报告成功、缺 ACK/缺反馈/缺任一轴到位时拒绝 OK、原始 ERROR 和广播 ACK 不适用。完整离线回归：`bash sim/run_regression_wsl.sh`。

G3 起步的 `diagnose` CLI mock 验证六轴只读成功、校验通过但舵机 ERROR 非零时保留原始错误字节与位置、其他 READ 故障时标记位置不可用，并确认 `--execute` 被拒绝且不触发 G2 WRITE。

ABI 13 的故障字节锁存能力在 ABI 14 保留：相对标定或 stop 的发前 READ、单播 WRITE 应答和发后 READ 均检查故障 ID、阶段及 `DIAG[23:16]`，下一次显式提交须清除旧诊断。绝对命令没有发前 READ 阶段。CLI mock 确认广播故障输出 `servo_error_raw`，同时保持 `unicast_ack=NOT_APPLICABLE_BROADCAST`。
