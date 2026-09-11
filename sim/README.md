# Verification plan（验证计划）

Add simulation artifacts in phases; keep testbenches independent from board-specific pin constraints.（分阶段加入仿真产物；测试平台必须独立于板级特定的引脚约束。）

1. `tb_axi_lite_regs`: reset, read ID/version, partial-write behavior, all six target registers, read/write response handshake.（复位、读取 ID/版本、部分写行为、全部六个目标寄存器及读/写应答握手。）
2. `tb_hx_packet`: byte-level checksum, PING, READ, WRITE, SYNC WRITE and malformed frames using protocol golden vectors.（使用协议黄金向量测试字节级校验和、PING、READ、WRITE、SYNC WRITE 和畸形帧。）
3. `tb_half_duplex_phy`: 1 Mbps 8N1 timing, direction turnaround and no-drive-after-E-stop assertions.（1 Mbps、8N1 时序、收发方向切换，以及急停后不得驱动总线的断言。）
4. `tb_motion_safety`: simultaneous six-axis descriptor commit, deadline miss, watchdog, limit and feedback-timeout behavior.（同时提交六轴描述符、截止超期、看门狗、限位和反馈超时行为。）

Every test should be executable from a script in this directory and should state the simulator/version used. Do not claim a waveform-only pass as real servo validation.（每项测试均应能由本目录脚本执行并注明所用仿真器/版本；只有波形通过不能宣称已完成真实舵机验证。）
