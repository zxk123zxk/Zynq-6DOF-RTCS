# G1 PL 直连实物基线（ABI 0x52540002）

归档日期：2026-10-05。此目录保存重新分配 J20 针位前的实际镜像与硬件产物；用户确认下列 SD 镜像就是本次实物验收所用版本。旧接线为 J20-33/U20 禁发跳线、J20-35/V15 TX、J20-36/W15 RX、J20-37 GND。

| 文件 | SHA-256 |
| --- | --- |
| BOOT.BIN | `670156ab3551be01c42c8c1d1fdbcd5518c5d6b5eee940c6ecb20a2cfecee681` |
| image.ub | `855203f8d7360c5b375910eebf8c8f30dc80352921bfae2a4e2b1a5fdcb71de6` |
| boot.scr | `065de2aa63e445f30b6aadd82b4f93c4a291a2c7e207d0b3d2ad3209d570cba5` |
| rtcs_system.bit | `7bdd862f410d7d2332490c671e9d72abc39d912a66418fee5b18c86ff2b840bc` |
| rtcs_system.xsa | `0bfc31d4c21a44ad99e06376dd44d3507c55d89b6d5c2d48703a04b357c9ad54` |
| SHA256SUMS | `fda55d8f63a927badcb6ad6777c9703918f52708abd3d5bcfaefd8cde3f51dc0` |

用户报告的板上结果：UIO 为 `rtcs / 0x43c00000 / 0x00010000`；`probe` 读到 `0x52540002`，未装 J20-33↔38 跳线时 `physical_tx=DISABLED`，装上后为 `ENABLED`；对 ID 1 的单播 PING 和当前位置 READ 成功，后者返回 `position_raw=2038`。断开 ID 1 舵机总线而 BusLinker 保持工作时，PING 与 READ 均返回 `ERR pl_fault=3`。依这些功能证据，PL 直连 G1 标记为通过。

证据边界：没有仪器测得的 Bank34 VCCIO 或 BusLinker TTL TX 空闲电压数值；用户确认舵机与板卡独立供电、可切断，但没有归档独立开关/急停切断后的实测结果。原理图的 3.3 V 设计信息不写作电压实测。G1 通过不授权 G2 实物运动或任何总线写入指令。
