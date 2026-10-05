# Verification plan（验证计划）

Add simulation artifacts in phases; keep testbenches independent from board-specific pin constraints.（分阶段加入仿真产物；测试平台必须独立于板级特定的引脚约束。）

1. `tb_axi_lite_regs`: reset, read ID/version, partial-write behavior, all six target registers, read/write response handshake.（复位、读取 ID/版本、部分写行为、全部六个目标寄存器及读/写应答握手。）
2. `tb_hx30hm_protocol`: HX-30HM PING/READ/goal-position WRITE checksum golden vectors. It validates only packet arithmetic, never physical output.（HX-30HM PING/READ/目标位置 WRITE 校验和黄金向量；仅验证报文运算，不验证物理输出。）
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
```

`tb_axi_lite_regs.sv` verifies synchronous reset, read-only register reads, AW-first/W-first/same-cycle writes, held B/R responses, non-contiguous byte writes, and independent readback of all six target registers. A successful run ends with `TB_AXI_LITE_REGS_PASS`.

（中文：`tb_axi_lite_regs.sv` 覆盖同步复位、只读寄存器、AW 先到/W 先到/同周期写、保持的 B/R 应答、非连续字节写以及六轴目标寄存器独立读回；成功时输出 `TB_AXI_LITE_REGS_PASS`。）

Every test should be executable from a script in this directory and should state the simulator/version used. Do not claim a waveform-only pass as real servo validation.（每项测试均应能由本目录脚本执行并注明所用仿真器/版本；只有波形通过不能宣称已完成真实舵机验证。）

`sim/tb_hx30hm_g1_engine.sv` checks 1 Mbps PING/READ frames, valid replies,
invalid ID/opcode and missing-response timeout without any servo connection.
`sim/tb_rtcs_g1_safe_top.sv` drives G1 commands through AXI and checks that
the safe top still fixes `servo_tx_en=0` and `servo_tx=1` throughout internal
UART activity. This does not validate electrical levels or real servo replies.
`sim/tb_rtcs_g1_ttl_top.sv` checks default inhibit, physical TX activation
only after the separate strap is grounded, immediate TX release on inhibit,
transaction abort and no automatic resume. Real servo replies remain an
on-board test described in the SD guide.
`sim/tb_g2_descriptor_guard.sv` checks atomic six-axis capture and rejection
of uncalibrated, out-of-range, faulted, inhibited and expired descriptors.
The guard is not wired to the physical servo UART. In WSL, run
`bash sim/run_pl_g1_cli_abi.sh` to verify the Linux CLI rejects ABI 02 before
register writes and accepts ABI 03 for a read-only `probe`.
