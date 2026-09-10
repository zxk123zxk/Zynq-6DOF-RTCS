# Verification plan

Add simulation artifacts in phases; keep testbenches independent from board-specific pin constraints.

1. `tb_axi_lite_regs`: reset, read ID/version, partial-write behavior, all six target registers, read/write response handshake.
2. `tb_hx_packet`: byte-level checksum, PING, READ, WRITE, SYNC WRITE and malformed frames using protocol golden vectors.
3. `tb_half_duplex_phy`: 1 Mbps 8N1 timing, direction turnaround and no-drive-after-E-stop assertions.
4. `tb_motion_safety`: simultaneous six-axis descriptor commit, deadline miss, watchdog, limit and feedback-timeout behavior.

Every test should be executable from a script in this directory and should state the simulator/version used. Do not claim a waveform-only pass as real servo validation.
