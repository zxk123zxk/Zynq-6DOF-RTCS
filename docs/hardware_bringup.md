# Hardware bring-up checklist

This checklist is a required gate, not optional documentation. Record measurement files under `data/` when the format is decided; do not commit personal or unverified raw captures by default.

## G0: board and power

- [ ] Confirm AX7020 PCB revision and exact XC7Z020 speed/package from board markings/schematic.
- [ ] Confirm PL bank voltage and the UART transceiver's compatible logic levels.
- [ ] Use a dedicated, measured servo supply. Never power six servos from a Zynq GPIO rail.
- [ ] Confirm common ground and measure idle bus voltage.
- [ ] Confirm E-stop physically removes/blocks actuation independently of software.

## G1: one servo protocol bench test

- [ ] Isolate one servo; record its ID and powered idle current.
- [ ] Capture a 1 Mbps 8N1 PING waveform and validate checksum.
- [ ] Issue one `READ` of position at address `0x38`, length 2; record received bytes and response timeout.
- [ ] Keep `servo_tx_en=0` in FPGA until PHY direction control and high-impedance release timing are demonstrated.
- [ ] Test malformed frame, checksum error, no-response timeout and cable disconnect.

## G2: arm calibration

- [ ] Build a six-axis ID table including mechanical joint, bus ID, zero count, direction, safe min/max, and home pose.
- [ ] Confirm target-position write base `0x2A` and six-byte payload (position, time, speed) against an actual HX-30HM response.
- [ ] Test `SYNC WRITE` only at low speed and clear workspace.
- [ ] Treat `SYNC READ` as unsupported until all six replies are ordered and checksum-valid on the real bus.

## G3: integrated safety tests

- [ ] Verify PL reset, AXI software stop, watchdog timeout and hardware E-stop all prevent transmit.
- [ ] Verify command deadline-miss, joint limit, checksum failure and feedback timeout are logged and observable to PS.
- [ ] Run 100 static cycles, recording success/failure, maximum position error and human interventions.
