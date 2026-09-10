# HLS reservation

Do not start with an HLS-only implementation. The first PL release uses RTL for AXI integration, bus arbitration, UART packet framing/parser, watchdog and safety logic.

After the RTL motion command path is measured, a Vitis HLS C++ experiment may replace only the numeric trapezoidal/S-curve profile kernel. It must retain the register contract, provide an RTL-equivalent testbench, and beat or match the RTL baseline on the stated latency/resource metric before adoption.
