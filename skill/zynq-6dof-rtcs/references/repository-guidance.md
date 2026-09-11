# Repository and reference guidance

## Active project source of truth

Use these paths for the AX7020/XC7Z020 implementation:

- `src/pl/rtl/`: `rtcs_top.sv` integration; `axi_lite_regs.sv` control-plane register bank; `trajectory_engine.sv`, `servo_bus_master.sv`, and `safety_monitor.sv` deterministic control boundaries; `rtcs_pkg.sv` shared RTL definitions.
- `src/ps/linux/`: UIO/MMIO application, shared register definitions, and CMake build.
- `docs/architecture.md`: PS/PL ownership, command lifecycle, safety invariants, and G0–G4 gates.
- `docs/register_map.md`: PS/PL register contract. Update it when an observable register interface changes.
- `config/`: measured calibration and arm/bus data only; `arm_calibration.template.toml` is a template, not verified physical data.
- `sim/`: RTL/protocol testbench and result material. `scripts/`: reproducible inspection and verification helpers.
- `src/pl/vivado/create_project.tcl` and `src/pl/xdc/ax7020_template.xdc`: build and board-constraint inputs. Pin assignments remain placeholders until verified against the exact AX7020 schematic.

## Material_Library: permitted references, not dependencies

`Material_Library/mycpu--/` is an independent RISC-V SoC with an RT-Thread Nano port. It can inform self-contained RTL organization, simulation/testbench patterns, FPGA build structure, MMIO trace/debugging, and RTOS-port investigation. It does not define the AX7020 robot architecture, its AXI interface, or its servo protocol.

Start with these paths only when relevant:

- `Material_Library/mycpu--/AGENTS.md` for local constraints and current validation context.
- `Material_Library/mycpu--/rtl/`, `tb/`, `tests/`, `tools/`, and `docs/` for RTL, verification, utilities, and RT-Thread-related evidence.

`Material_Library/kr260_robotic_arm-main/` is a complete KR260/ROS2 project with a USB-serial/PWM six-axis arm. It can inform high-level camera, color-recognition, ROS2-node, and demo-workflow ideas. Its board, Ubuntu/ROS stack, PWM actuator interface, and USB serial transport are incompatible with this AX7020/HX-30HM half-duplex servo-bus design.

Start with these paths only when relevant:

- `Material_Library/kr260_robotic_arm-main/README.md` for the project boundary and operator workflow.
- `Material_Library/kr260_robotic_arm-main/opencv_ros2/` and `vision_opencv/` for vision/ROS2 examples.
- `Material_Library/kr260_robotic_arm-main/如何启动KR260.md` and `如何在KR260上运行ROS.md` for KR260-specific environment procedures.

Before adapting any reference behavior, explain the platform/interface difference, reimplement the necessary logic in the active project's conventions, and record provenance/license questions. Never claim a reference-project test validates this controller.
