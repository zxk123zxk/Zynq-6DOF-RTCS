# 当前 SD 镜像与板端命令

当前匹配版本为 ABI 0x5254000C。J20-35/V15 接 BusLinker TX，J20-33/U20 接 BusLinker RX，J20-37 共地；J20-36/W15 到 J20-38/GND 是物理允许跳线。独立舵机电源开关与该跳线分开。所有舵机运动只由板端操作者执行。

## 交付文件

2026-10-08 构建 Vivado 2023.2 bitstream/XSA，2026-10-09 用最终两套 G2 CLI 重建 PetaLinux rootfs 和 SD 文件。Vivado 核对 TX=U20、RX=V15、禁发=W15、唯一 OBUFT；setup/hold 最差裕量为 0.246/0.068 ns，无失败端点。XSA 内嵌 bitstream 与独立 bitstream 哈希一致，PetaLinux 的 system.bit 与独立文件逐字节一致；rootfs 包含 G1、G2 单轴和 G2 六轴 CLI。

| 文件 | SHA256 |
| --- | --- |
| [rtcs_system.bit](../artifacts/hw/rtcs_system.bit) | e01578f5c448c40e61298d20d40073bfb8fd89b4d449bc5beb4a78ebca5c9971 |
| [rtcs_system.xsa](../artifacts/hw/rtcs_system.xsa) | 7eeb8f6e364342dc4244bb80572d30b7bb1a688c7c3f0c9d0336f6b61d0847ef |
| [BOOT.BIN](../artifacts/sd/BOOT.BIN) | 29c49ec70aab6492ef06bb425b8cb31807ed5266ea0443b065079dd5c04b74f7 |
| [image.ub](../artifacts/sd/image.ub) | 55f89f7f7d2711b794f518ede8d2618ed18f0d8b070decb1fc3106c54ded7eef |
| [boot.scr](../artifacts/sd/boot.scr) | 11242ad17e37ff52e9c1da2d9b5a668dfb4f819c34134f9d61ceaab45e153c52 |

复制三个 SD 文件到 FAT32 启动分区；复制前后按 [SHA256SUMS](../artifacts/sd/SHA256SUMS)核对。源码重建入口为 [Vivado 脚本](../scripts/build_vivado.ps1)的 Build/Ttl 选项，以及 [PetaLinux XSA 导入](../scripts/petalinux/create_project.sh)和 [SD 打包](../scripts/petalinux/build_sd_image.sh)。旧 ABI 镜像和 CLI 不混用。

## 核心板端验收代码

1. **不装物理允许跳线**，运行只读命令，核对 ABI、禁发及六轴限位：

       sudo rtcs-pl-g1 --uio /dev/uio0 probe
       sudo rtcs-pl-g2-six --uio /dev/uio0 limits

   应有 id_version=0x5254000c、physical_tx=DISABLED、calibrated_mask=0x3f；逐轴 min/max/reference_count/speed_raw_max 必须与 [实测配置](../config/g2_measured_limits.toml)一致。参考位置不是自动安全回位目标。

2. 清空工作空间、核对关节支撑与电源后，装上允许跳线并重新 probe，再只读清点：

       sudo rtcs-pl-g1 --uio /dev/uio0 probe
       sudo rtcs-pl-g2-six --uio /dev/uio0 inventory

   应有 physical_tx=ENABLED 和六个唯一 ID 的本次实时位置。下面的尖括号是占位符，必须由操作者根据这次读数、机械空间和实测闭区间逐项替换，不能直接运行：

       sudo rtcs-pl-g2-six --uio /dev/uio0 move-six \
         --axis 1:<目标1>:500:10 --axis 2:<目标2>:500:10 \
         --axis 3:<目标3>:500:10 --axis 4:<目标4>:500:10 \
         --axis 5:<目标5>:500:10 --axis 6:<目标6>:500:10 \
         --observe-ms 5000 --execute

   默认容差为各轴 ±30 count，可用 --tolerance ID:N 在 1–100 count 内显式设置。核对 write_sent=1、unicast_ack=NOT_APPLICABLE_BROADCAST、fault=0、每轴 start/target/last/actual_delta/target_error；重复提交前重新 inventory。位置变化与到位是两项不同证据。

3. 越限拒绝测试仅在已完成正常同步写后进行。重新 inventory，其余五轴填写当次位置，故意给 ID 2 写 860（实测下限 861）。应在发前报 ERR axis=2 target_or_speed_outside_pl_limit，不出现 commit 或动作。

       sudo rtcs-pl-g2-six --uio /dev/uio0 move-six \
         --axis 1:<本次位置1>:500:10 --axis 2:860:500:10 \
         --axis 3:<本次位置3>:500:10 --axis 4:<本次位置4>:500:10 \
         --axis 5:<本次位置5>:500:10 --axis 6:<本次位置6>:500:10 --execute

4. 软件停止测试由操作者在受控运动中执行，并记录请求到实际停止的延迟：

       sudo rtcs-pl-g2-six --uio /dev/uio0 stop --execute

   只有出现 RTCS_PL_G2_SIX_OK command=stop 才算软件停止成功。fault 5 必须看 fault_id、phase、engine_fault 和 write_sent，以区分保持广播前后的 READ 失败。独立断电急停另行在支撑受载关节的条件下实测，软件 stop 不能代替它。

任一 ABI/限位不符、ID 缺失、物理禁发状态异常、ERR、干涉或异常动作均停止后续提交并保留日志；故障不会自动重试。G2 阶段总结与核心文件目录见 [G2 说明](2.G2-six-axis-calibration.md)。原多版本操作记录保存在 [历史快照](history/SD-through-ABI12-20261009.md)。
