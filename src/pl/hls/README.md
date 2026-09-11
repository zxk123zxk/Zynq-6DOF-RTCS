# HLS reservation（HLS 预留说明）

Do not start with an HLS-only implementation. The first PL release uses RTL for AXI integration, bus arbitration, UART packet framing/parser, watchdog and safety logic.
（不要从纯 HLS 实现开始。首个 PL 版本以 RTL 实现 AXI 集成、总线仲裁、UART 数据包封装/解析、看门狗和安全逻辑。）

After the RTL motion command path is measured, a Vitis HLS C++ experiment may replace only the numeric trapezoidal/S-curve profile kernel. It must retain the register contract, provide an RTL-equivalent testbench, and beat or match the RTL baseline on the stated latency/resource metric before adoption.
（在 RTL 运动命令路径完成测量后，Vitis HLS C++ 实验仅可替换数值型的梯形/S 曲线轨迹内核。它必须保留寄存器契约、提供等价 RTL 测试平台，并在指定延迟/资源指标上达到或优于 RTL 基线后才能采用。）
