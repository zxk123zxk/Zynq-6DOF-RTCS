# ABI 11 构建产物归档

ABI 12 修改前复制了工作区中已有的 ABI 11 bitstream、XSA、SD 三件套及原 `SHA256SUMS`。不得将此处旧镜像与 ABI 12 CLI 混用。

| 文件 | SHA256 |
| --- | --- |
| `hw/rtcs_system.bit` | `7a2b5f9232d63261de66daa5cb8578b9aa5d2d8f139745be398a73534abef7de` |
| `hw/rtcs_system.xsa` | `b124d56cf74b44c4348a5f51e1056c2a1668bd7aa54615d50ecc6274c3d7fa4d` |
| `sd/BOOT.BIN` | `5acfde6dfe870bb13f7ab4a17fb62741461641f88e1d381d29c5f3df89674ccf` |
| `sd/image.ub` | `626b2d9c2c1936fb26cc7209e93f8b71d780c7bb4bd8b7e464472b2d9980e632` |
| `sd/boot.scr` | `835b509ffa6180f250dff13b9f7fb70e6d03e5f12037292b583bf2dec054b8cc` |

用户报告 ABI 11 的 ID 2 曾因外物阻挡，WRITE 已发且单播应答成功，反馈只变化 9 count 并报告 fault 9；障碍随后移除。此证据不能推断舵机未开扭矩，也不能把 ACK 当作到位。ABI 11 的持久故障锁会阻断下一次六轴 SYNC，ABI 12 已改为逐命令故障报告。
