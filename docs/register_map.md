# RTCS AXI4-Lite register map v0

All registers are 32-bit, little-endian and based at the address assigned to `rtcs_top` by Vivado. This is a **versioned interface contract**; PS code must include `rtcs_registers.hpp`, never duplicate numeric offsets.

| Offset | Name | Access | Definition |
| ---: | --- | --- | --- |
| 0x00 | ID_VERSION | RO | `0x5254_0001` (`RT`, interface revision 1) |
| 0x04 | CONTROL | RW | bit 0: global enable request; bit 1: clear latched faults; bit 2: soft stop request |
| 0x08 | COMMAND | WO | bit 0: enqueue descriptor; bits 31:16: PS sequence tag |
| 0x0c | STATUS | RO | bit 0: implementation-safe/disabled; future: busy, FIFO full, fault, deadline miss |
| 0x10 | IRQ_STATUS | RO in phase 0; RW1C final | completion/fault/deadline IRQ causes; no source is implemented yet |
| 0x14 | HW_TICKS_LO | RO | free-running 100 MHz-domain tick counter, lower 32 bits |
| 0x18 | HW_TICKS_HI | RO | free-running tick counter, upper 32 bits |
| 0x20..0x34 | TARGET_0..TARGET_5 | RW | signed joint command units; unit is not valid until calibration format is ratified |
| 0x38 | PROFILE_SPEED | RW | requested common profile speed; unit pending calibration |
| 0x3c | PROFILE_ACCEL | RW | requested common profile acceleration; unit pending calibration |
| 0x40 | DEADLINE_LO | RW | absolute PL tick deadline, lower 32 bits |
| 0x44 | DEADLINE_HI | RW | absolute PL tick deadline, upper 32 bits |
| 0x48 | SERVO_CONFIG | RW | protocol options; bit 0 may later select verified SYNC READ |
| 0x4c | DEBUG | RO | implementation-specific diagnostics |

### Write order

Write descriptor fields first, then write `COMMAND.ENQUEUE=1` last. A later implementation will ignore an enqueue unless global enable, calibration-valid and safety conditions are all true. Current skeleton accepts and exposes fields only; it produces no motion.

### Phase-0 implementation status

The skeleton implements the ID, control/command storage, tick counter, target/profile/deadline storage and `SERVO_CONFIG` storage. `STATUS` reports safe-disabled and `IRQ_STATUS` is read-only zero. Motion, FIFO, error sources and IRQ write-one-to-clear behavior are reserved for the next PL milestone.

### Interrupt policy

IRQ output remains low in the skeleton. The final implementation will use level-sensitive `IRQ_STATUS` with write-one-to-clear acknowledgement, enabling a UIO interrupt path without a custom Linux kernel driver in the first phase.
