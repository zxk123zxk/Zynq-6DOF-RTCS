# ABI 10 构建产物归档

本目录在 ABI 11 修改和重建之前，复制了当前未提交的 ABI 10 bitstream、XSA、SD 三件套和原 `SHA256SUMS`。复制品的 SHA256 如下；后续不得将它们与 ABI 11 CLI 混用。

| 文件 | SHA256 |
| --- | --- |
| `hw/rtcs_system.bit` | `3485c613a8da90ba3947aaf8760064f0326b461ccc7ac011c47cb2e4496430b3` |
| `hw/rtcs_system.xsa` | `91ec13faa82e7796151c2a8e04e32da791491250bbe4e0a57c2e485197d1440e` |
| `sd/BOOT.BIN` | `1cf4a3824229bcfa92d3d516174db7a5ae0a1975aa0be88e8844433b5ba6a959` |
| `sd/image.ub` | `a5ece573e0fc9f378c3c016f776d21796fce9dba24f25c13c834bf808997ba66` |
| `sd/boot.scr` | `bf8a17bbb9bb3b804c8b7481a8682fd8135fb5d114a06f9e09180beb395b7150` |

用户已在 ABI 10 板端逐轴测得回零位置和安装状态下安全范围，随后报告的 `move-six` 输出为 `calibrated_mask=0x00 fault_latched=1`，并报 `ERR six_axis_uncalibrated`。这次拒绝没有发送 SYNC WRITE；故障锁还需在排查后通过 PL 复位清除。完整六轴同步实物验收尚未发生。
