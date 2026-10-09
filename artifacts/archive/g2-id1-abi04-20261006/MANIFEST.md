# ABI 04 ID 1 首次试动归档（2026-10-06）

本目录在 ABI 05 构建前保存 ABI 04 的 bitstream、XSA 和三份 SD 启动文件。`SHA256SUMS` 对应本目录内的三份 SD 文件。

上板实测接线：J20-33/U20（PL RX）接 BusLinker TTL 丝印 **TX**；J20-35/V15（PL TX）接丝印 **RX**；J20-37 接 GND；J20-36/W15 与 J20-38/GND 接禁发跳线。该接线实测 PING、READ 成功；不要按早期文档反接。

ABI 04 首次 ID 1 试动的原始 2 秒验收**未通过**：CLI 报 `fault=9`，最后一次反馈为 `1999`。随后另行执行的 `READ_POSITION` 为 `2006`；这只能证明稍后读到 2006，不能推断目标在原 2 秒期限内到达，也不能认作零位。该版没有自动补发 WRITE 的证据，不能据后读数把原结果改记为通过。

| 文件 | SHA256 |
| --- | --- |
| `BOOT.BIN` | `4fe99c9603a5cda562f1e27aa12bcdf46c36f939fd2bea1151cb3213ece598b1` |
| `image.ub` | `7180655174d2e9c114ba8613ed2b99aea61f8196b660536ec9b82accd5b9f1dd` |
| `boot.scr` | `1b635871a7e6b412a75679c77bde056a0fd991410a4422c612e1c69c35770b76` |
| `rtcs_system.bit` | `9eac97abe76dc3e9cb4e54c2b6e3a1af6bc19254818cdfeaf74fad703a89f162` |
| `rtcs_system.xsa` | `09fbf37b7b8276a97a32a2a1ff95c69cd82f420487d1a64ae0c8afe030d2b890` |
