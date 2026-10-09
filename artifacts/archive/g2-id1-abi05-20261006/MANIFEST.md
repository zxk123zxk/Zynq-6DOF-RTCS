# ABI 05 ID 1 G2 试动归档（2026-10-06）

本目录保存改为 ABI 06 前的 bitstream、XSA 和三份 SD 启动文件。`SHA256SUMS` 是这些文件的归档校验值，不能与 ABI 06 混用。

用户已将 ABI 05 镜像上板。G2 显示 `one_shot=AVAILABLE`；CLI 预读位置 `pre_read_position_raw=2006` 后报 `ERR start_outside_1990_2000; no WRITE sent`。本次拒绝没有消耗一次性 WRITE，也没有新的运动证据。

当时沿用已验证的接线：J20-35/V15（PL TX）→BusLinker RX，J20-33/U20（PL RX）←BusLinker TX，J20-37↔GND；J20-36/W15↔J20-38/GND 为独立允许跳线。ABI 06 将交换两个信号引脚的 PL 方向，新接法不能套用于本归档镜像。
