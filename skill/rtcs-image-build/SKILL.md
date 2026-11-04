---
name: rtcs-image-build
description: Build the Zynq-6DOF-RTCS Vivado hardware and PetaLinux SD image when a request starts with “镜像构建：” or invokes $rtcs-image-build. Do not use for image editing or other repositories.
---

# RTCS 镜像构建

`镜像构建：` 表示按**当前仓库源码**执行完整本地构建；冒号后的内容是本次约束或指定的现有 PetaLinux 项目路径。没有明确的源码修改要求时，不改源码。此触发仅授权更新仓库 `artifacts/` 内的生成物及现有 PetaLinux 项目的构建结果；不授权写实体 SD 卡、QSPI、下载到板卡、连接或发送舵机指令。

1. 确认当前仓库是 `Zynq-6DOF-RTCS`，检查 `git status --short`，保留已有未提交改动。读取当前的 `scripts/build_vivado.ps1`、`scripts/petalinux/create_project.sh`、`scripts/petalinux/build_sd_image.sh` 及 `artifacts/` 结构；以脚本**实际参数**为准，不凭记忆改用 `--sync-only`。核实 Vivado 2023.2、WSL PetaLinux 2023.2 和现有项目路径。本机通常为 WSL `Ubuntu-22.04`、设置脚本 `$HOME/tools/petalinux/2023.2/settings.sh`、项目 `$HOME/projects/zynq/petalinux-rtcs`，但每次先验证；找不到时询问，不臆造或清空项目。
2. 在仓库根目录运行 `powershell -ExecutionPolicy Bypass -File scripts/build_vivado.ps1 -Build`。只有进程退出码为零，且 `artifacts/hw/rtcs_system.bit`、`artifacts/hw/rtcs_system.xsa` 非空，`artifacts/reports/timing_summary.rpt`、`utilization.rpt`、`methodology.rpt` 均存在并确认时序满足后，才继续。失败时停止，指出 `artifacts/logs/vivado.log` 或实现 run log；旧文件存在不算本次成功。
3. 在 WSL 中 source 已验证的 PetaLinux 2023.2 settings，调用仓库 `scripts/petalinux/create_project.sh --import-hw <现有项目路径>`，把**新 XSA**导入现有项目。不得以 `--sync-only` 代替硬件导入；不得删除项目、BitBake/sstate 缓存或覆盖用户的 rootfs 选择。
4. 同一 PetaLinux 环境调用 `scripts/petalinux/build_sd_image.sh <现有项目路径>`。只在退出码为零并出现 `RTCS_SD_OK` 后，核对 `artifacts/sd/BOOT.BIN`、`image.ub`、`boot.scr`、`SHA256SUMS` 四个非空文件，并在该目录执行 `sha256sum -c SHA256SUMS`。日志应留在 `artifacts/logs/`。阶段失败即停止，不用前次生成物凑齐交付。
5. 简洁报告实际完成情况：Vivado 时序 WNS/TNS、bit/XSA 路径与大小、四个 SD 文件及 SHA-256、所用 PetaLinux 项目路径、未完成的验证。仅构建镜像不能宣称板卡启动、USB 枚举或舵机已验证；不要自动写卡。

避免另写一套构建命令或修改无关文件。构建可能耗时，期间提供简短进度更新；若环境权限或工具不可用，明确阻断阶段并保留已有产物，不假报成功。
