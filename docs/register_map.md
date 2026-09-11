# RTCS AXI4-Lite register map v0（RTCS AXI4-Lite 寄存器映射 v0）

All registers are 32-bit, little-endian and based at the `rtcs_top` address fixed by G0 Vivado to **`0x43C0_0000`** (64 KiB aperture). This is a **versioned interface contract**; PS code must include `rtcs_registers.hpp`, never duplicate numeric offsets.

（中文：全部寄存器均为 32 位小端格式，基址由 Vivado 分配给 `rtcs_top`。这是**带版本的接口契约**；PS 代码必须包含 `rtcs_registers.hpp`，不能自行重复定义数值偏移。）

| Offset（偏移） | Name（名称） | Access（访问） | Definition（定义） |
| ---: | --- | --- | --- |
| 0x00 | ID_VERSION | RO（只读） | `0x5254_0001` (`RT`, interface revision 1：接口修订版 1) |
| 0x04 | CONTROL | RW（读写） | bit 0: global enable request（全局使能请求）；bit 1: clear latched faults（清除锁存故障）；bit 2: soft stop request（软件停止请求） |
| 0x08 | COMMAND | WO（只写） | bit 0: enqueue descriptor（描述符入队）；bits 31:16: PS sequence tag（PS 序列标签） |
| 0x0c | STATUS | RO（只读） | bit 0: implementation-safe/disabled（实现安全禁用）；future: busy, FIFO full, fault, deadline miss（后续：忙、FIFO 满、故障、截止超期） |
| 0x10 | IRQ_STATUS | RO in phase 0; RW1C final（第 0 阶段只读；最终版写 1 清除） | completion/fault/deadline IRQ causes; no source is implemented yet（完成/故障/超期中断原因；当前尚无中断源） |
| 0x14 | HW_TICKS_LO | RO（只读） | free-running 100 MHz-domain tick counter, lower 32 bits（100 MHz 时钟域自由运行计数器低 32 位） |
| 0x18 | HW_TICKS_HI | RO（只读） | free-running tick counter, upper 32 bits（自由运行计数器高 32 位） |
| 0x20..0x34 | TARGET_0..TARGET_5 | RW（读写） | signed joint command units; unit is not valid until calibration format is ratified（有符号关节命令单位；标定格式批准前单位无效） |
| 0x38 | PROFILE_SPEED | RW（读写） | requested common profile speed; unit pending calibration（请求的公共轨迹速度；单位待标定） |
| 0x3c | PROFILE_ACCEL | RW（读写） | requested common profile acceleration; unit pending calibration（请求的公共轨迹加速度；单位待标定） |
| 0x40 | DEADLINE_LO | RW（读写） | absolute PL tick deadline, lower 32 bits（绝对 PL 时钟截止时间低 32 位） |
| 0x44 | DEADLINE_HI | RW（读写） | absolute PL tick deadline, upper 32 bits（绝对 PL 时钟截止时间高 32 位） |
| 0x48 | SERVO_CONFIG | RW（读写） | protocol options; bit 0 may later select verified SYNC READ（协议选项；bit 0 后续可选择已验证的同步读） |
| 0x4c | DEBUG | RO（只读） | implementation-specific diagnostics（实现特定诊断信息） |

### Write order（写入顺序）

Write descriptor fields first, then write `COMMAND.ENQUEUE=1` last. A later implementation will ignore an enqueue unless global enable, calibration-valid and safety conditions are all true. Current skeleton accepts and exposes fields only; it produces no motion.

（中文：先写描述符字段，最后写 `COMMAND.ENQUEUE=1`。后续实现只有在全局使能、标定有效和安全条件均满足时才接受入队。当前骨架只存储和暴露字段，不会产生运动。）

### Phase-0 implementation status（第 0 阶段实现状态）

The skeleton implements the ID, control/command storage, tick counter, target/profile/deadline storage and `SERVO_CONFIG` storage. `STATUS` reports safe-disabled and `IRQ_STATUS` is read-only zero. Motion, FIFO, error sources and IRQ write-one-to-clear behavior are reserved for the next PL milestone.

（中文：骨架实现了 ID、控制/命令存储、时钟计数器、目标/轨迹/截止时间存储和 `SERVO_CONFIG` 存储。`STATUS` 报告安全禁用，`IRQ_STATUS` 为只读零。运动、FIFO、错误源和中断写 1 清除均留给下一 PL 里程碑。）

### Interrupt policy（中断策略）

IRQ output remains low in the skeleton. The final implementation will use level-sensitive `IRQ_STATUS` with write-one-to-clear acknowledgement, enabling a UIO interrupt path without a custom Linux kernel driver in the first phase.

（中文：骨架中的 IRQ 输出保持低电平。最终实现会采用电平敏感的 `IRQ_STATUS` 和写 1 清除确认机制，使第一阶段无需自定义 Linux 内核驱动即可走 UIO 中断路径。）
