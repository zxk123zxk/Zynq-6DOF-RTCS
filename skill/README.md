# 可复用技能：AXI 控制的实时外设 bring-up

## Scope / 适用范围

Use this template when integrating a PS/Linux application with a custom AXI4-Lite PL peripheral that controls physical hardware. It applies to motors, sensors and buses; it does not assume this robot or board.

## Workflow / 工作流

1. Define a versioned register map before RTL/host code diverges.
2. Keep physical outputs disabled by reset and by an independent safety gate.
3. Test bus/protocol behavior with one device and a logic analyzer before multi-device operation.
4. Require an atomic descriptor commit register; never act on a partially written vector.
5. Measure and log latency, jitter, timeout and fault paths alongside nominal behavior.
6. Preserve a host-only baseline to quantify why PL improves the target metric.

## Inputs and outputs / 输入与输出

Inputs: device protocol, board schematic, chosen AXI clock, safety requirements, and a host-access mechanism (UIO or driver).

Outputs: register-map header, RTL register bank, host smoke test, waveform capture, safety-test table and reproducible build command.

## Failure conditions / 失败条件

Do not use this workflow without verified IO voltage/direction control, measured safe limits, or a way to force output disable. AXI register access alone is not proof that a physical interface is safe.

## Evidence of derivation / 来源说明

This template was established while separating a Linux vision/planning layer from deterministic servo-bus logic for a Zynq-based robot. It is intentionally hardware-agnostic and will be updated only when its steps succeed on a second peripheral class.
