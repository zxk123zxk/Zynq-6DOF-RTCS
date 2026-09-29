# Verification plan（验证计划）

Add simulation artifacts in phases; keep testbenches independent from board-specific pin constraints.（分阶段加入仿真产物；测试平台必须独立于板级特定的引脚约束。）

1. `tb_axi_lite_regs`: reset, read ID/version, partial-write behavior, all six target registers, read/write response handshake.（复位、读取 ID/版本、部分写行为、全部六个目标寄存器及读/写应答握手。）
2. `tb_hx30hm_protocol`: HX-30HM PING/READ/goal-position WRITE checksum golden vectors. It validates only packet arithmetic, never physical output.（HX-30HM PING/READ/目标位置 WRITE 校验和黄金向量；仅验证报文运算，不验证物理输出。）
3. `tb_half_duplex_phy`: 1 Mbps 8N1 timing, direction turnaround and no-drive-after-E-stop assertions.（1 Mbps、8N1 时序、收发方向切换，以及急停后不得驱动总线的断言。）
4. `tb_motion_safety`: simultaneous six-axis descriptor commit, deadline miss, watchdog, limit and feedback-timeout behavior.（同时提交六轴描述符、截止超期、看门狗、限位和反馈超时行为。）

## AXI4-Lite register regression（AXI4-Lite 寄存器回归）

Run the following command from the repository root with Icarus Verilog installed. The checked-in runner uses `iverilog -g2012` and `vvp`; build products are written below ignored `artifacts/sim/`.

```powershell
powershell -ExecutionPolicy Bypass -File sim/run_axi_lite_regs.ps1
powershell -ExecutionPolicy Bypass -File sim/run_hx30hm_protocol.ps1
powershell -ExecutionPolicy Bypass -File sim/run_servo_rx_only.ps1
```

`tb_axi_lite_regs.sv` verifies synchronous reset, read-only register reads, AW-first/W-first/same-cycle writes, held B/R responses, non-contiguous byte writes, and independent readback of all six target registers. A successful run ends with `TB_AXI_LITE_REGS_PASS`.

（中文：`tb_axi_lite_regs.sv` 覆盖同步复位、只读寄存器、AW 先到/W 先到/同周期写、保持的 B/R 应答、非连续字节写以及六轴目标寄存器独立读回；成功时输出 `TB_AXI_LITE_REGS_PASS`。）

Every test should be executable from a script in this directory and should state the simulator/version used. Do not claim a waveform-only pass as real servo validation.（每项测试均应能由本目录脚本执行并注明所用仿真器/版本；只有波形通过不能宣称已完成真实舵机验证。）
