# ABI 09 上板前产物与实物摘要归档

本目录是在 ABI 10 构建前，从当前工作区复制的 ABI 09 bitstream、XSA、SD 三件套和原 `SHA256SUMS`；不覆盖原有未提交改动。以下 SHA256 对复制品重新计算。

| 文件 | SHA256 |
| --- | --- |
| `hw/rtcs_system.bit` | `27ad234a3bf9b120316fc676318da032657469e2268fede8680250dd0ad742b1` |
| `hw/rtcs_system.xsa` | `3f15dfbe88beab8e8b9afb394adfc81fd5a4545708f44f9fd8b0c74fb89eee65` |
| `sd/BOOT.BIN` | `72ad6996dfda38592757b1096200a0fda6d60f500fbe46f8e7abc850b551f064` |
| `sd/image.ub` | `2b2ad8fc819a818ea6dd1f5bc161e18302851ef42a032674b04188173a1a83a5` |
| `sd/boot.scr` | `11c5167c108d659eeae19ffda2badcb60735857b9e1b48989412a7b4722cea61` |

用户提供的 ABI 09 实物摘要：inventory 的 ID 1–6 依次为 `1990, 871, 3085, 2860, 1980, 1582`。ID 2 `calibrate-step +20` 现场起点 871、目标 891、反馈 877，报告 OK；它只走约 6 count，目标误差 14，符合 ABI 09 的旧 ±15 判据，不证明完成 20 count。ID 3–6 各 `+20` 均报 `fault=9, write_sent=1`。随后 `stop` 成功，六轴读数为 `1990, 876, 3086, 2861, 1980, 1586`。这些 stop 后读数不能单独归因于之前各次标定 WRITE。

ABI 09 `rtcs-pl-g2 move --id 2` 被 CLI 拒绝。用户提交的六个数字目标 `1990, 876, 3086, 2861, 1980, 1586` 被 `move-six` 以 `calibrated_mask=0x00` 拒绝，未发送同步运动帧。部分更早的尝试包含非数字目标，不能与该次硬件未标定拒绝混为一谈。原始完整逐次反馈日志未提供，本归档只记录用户给出的摘要，不补造采样。

代码审查确认，单播帧从 `0x28` 写 `1`，并在同一帧写入目标、原始时间和原始速度。单播协议应答成功后才开始反馈 READ；`fault 9` 的精确条件是 WRITE 启动后的 5 秒观察期内，未完成三次连续处于目标验收带的反馈。它不能单独证明扭矩未开启、舵机未动或机械故障。
