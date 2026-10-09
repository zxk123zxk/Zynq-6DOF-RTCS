# ABI 03 G1 只读实物归档

此目录保存用户上板验证过的 ABI `0x52540003` 三份 SD 文件与原 `SHA256SUMS`；不是本轮 ABI 04 G2 镜像。

用户报告的实物结果：J20-36↔38 接入后 `physical_tx=ENABLED`；ID 1 单播 PING 成功；当前位置 READ 为 `position_raw=1995`。不加 `sudo` 打开 `/dev/uio0` 报 `Permission denied`，加 `sudo` 成功。经用户再次确认，成功通信时接线为 J20-35/V15（PL TX）→BusLinker 丝印 RX、J20-33/U20（PL RX）←BusLinker 丝印 TX、J20-37↔GND。`1995` 仅为当次读数，不代表零位或标定。

本次没有仪器测得的 Bank34 VCCIO、TTL 空闲电压或独立电源开关切断结果；不把这些项目写成通过。归档文件复制后其 SHA256 与随附 `SHA256SUMS` 一致。
