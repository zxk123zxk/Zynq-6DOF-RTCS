# ABI 13 (0x5254000d) 产物归档 —— 故障归因改造重建之前

归档日期：2026-10-10。此目录保存**当前板端正在运行**的硬件与 SD 产物，即改用带
故障归因诊断的 CLI 之前那一版。文件哈希见 [SHA256SUMS](SHA256SUMS)。

| 文件 | 说明 |
| --- | --- |
| `rtcs_system.bit` | 板端实际加载的 PL（ABI `0x5254000d`，TTL 封装，`physical_tx=ENABLED`） |
| `rtcs_system.xsa` | 与该 bit 同批导出的 XSA |
| `BOOT.BIN` / `image.ub` / `boot.scr` | 2026-10-09 19:39 打包的 SD 三件套，板端日志 `abi=0x5254000d` 即出自这一版 |

## 为什么归档

操作者报告 ID 5 大幅移动报错（`--target 1000` 起点 1931、`--target 3000` 起点 2012，
均 `write_sent=1 unicast_ack=0 fault=8`；`--target 2000` 起点 2322 成功）。定位需要用
能区分“传输层故障”与“舵机自报非零 ERROR”的 CLI 复测，因此要重建 SD 镜像。
按本仓库既有惯例，重建前先把与板端一致的那一版产物原样保存，避免新旧文件混用。

## 边界说明

- 本次重建只改 CLI（`rtcs_pl_g2.c` / `rtcs_pl_g2_six.c` / `rtcs_servo_diag.h`）与
  PetaLinux 应用包，**bitstream 与 XSA 未重新综合**，因此新镜像的 PL 仍是本目录
  这份 `rtcs_system.bit`（ABI 0x0d）。
- PL 侧新增的 `G2_DIAG` 锁存（0x118）与半双工 RX 冲刷修复**不在此版本内**，
  需另行用 Vivado 重新综合后才能生效。
- 本目录的 `BOOT.BIN` / `image.ub` 与 `SHA256SUMS` 是 2026-10-09 那批的原件副本，
  其内部哈希指向同批文件；不要与重建后的 `artifacts/sd/` 混用。
