# Architecture and stage boundaries

## Fixed partition

| Layer | Owns | Must not own |
| --- | --- | --- |
| PS / Linux | camera, classification, calibration, coordinate conversion, FK/IK, task FSM, target prediction, deadline generation, logging | UART bit timing, servo bus arbitration, emergency timing |
| AXI contract | command descriptor, status, counters, IRQ acknowledgement | image buffers or high-rate feedback streams in phase 1 |
| PL / RTL | command buffering, trajectory timing, multi-axis issue, UART protocol, response parser, watchdog, limits and E-stop | model inference or high-level task policy |
| Servo | internal motor current/position loop | global task scheduling |

The first version intentionally uses AXI4-Lite for commands and status. If feedback bandwidth later proves insufficient, add AXI DMA only after measuring the limitation; do not introduce it speculatively.

## PL data path

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

## Command lifecycle

1. PS validates IK result, calibrated joint limits and a monotonic deadline.
2. PS writes all six target registers, profile registers and deadline.
3. PS writes `COMMAND` last with `ENQUEUE` set; this is the commit point.
4. PL atomically snapshots the descriptor, validates it, queues it and returns a sequence number.
5. The scheduler emits `SYNC WRITE` packets at the planned cadence; feedback is checked against timeout/error policy.
6. PL raises IRQ for completion, deadline miss, servo fault or safety fault. PS reads `IRQ_STATUS`, records the outcome, then acknowledges it.

This lifecycle prevents a partially written target vector from reaching a servo.

## Non-negotiable safety invariants

- Reset, watchdog expiry, hardware E-stop and illegal command all force bus transmit disable.
- Every limit in `config/` comes from a measured/calibrated arm; no guessed mechanical limits.
- Broadcast PING is prohibited because the HX protocol permits multiple replies on the same bus.
- `SYNC READ` is optional until demonstrated on all six physical servos; sequential `READ` is the baseline feedback path.

## Stage gates

| Gate | Required evidence | Enables |
| --- | --- | --- |
| G0 | AX7020 board/pin/supply verification | PS7 + AXI integration |
| G1 | logic-analyzer waveform for one servo PING/READ | TX enable for bench test |
| G2 | six ID/zero/limit records and isolated motion test | `SYNC WRITE` |
| G3 | RTL simulation + 100 static pick/place cycles | trajectory and feedback closed loop |
| G4 | moving-belt trial, deadline and P99-jitter data | final demo |
