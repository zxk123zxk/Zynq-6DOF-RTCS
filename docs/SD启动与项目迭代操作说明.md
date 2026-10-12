# 当前 SD 镜像与板端命令

本页记录的**已构建**镜像及下列哈希为 2026-10-12 离线重建的 ABI 0x5254000E；绝对目标不再要求发前 READ 成功。**该 ABI 已于 2026-10-12 上板实测**（`probe` 报 `abi=0x5254000e physical_tx=ENABLED`，ID 5 单轴远端运动成功，见 [G2](2.G2-six-axis-calibration.md)），不再禁止新旧混用——**但只允许使用本 ABI 0E 的 PL 与 CLI 组合，旧的 0D 组合一律弃用**。旧产物见[构建前归档](../artifacts/archive/g2-id5-angle-window-20261012/README.md)。J20-35/V15 接 BusLinker TX，J20-33/U20 接 BusLinker RX，J20-37 共地；J20-36/W15 到 J20-38/GND 是物理允许跳线。独立舵机电源开关与该跳线分开。所有舵机运动只由板端操作者执行。

## 交付文件

2026-10-12 用 Vivado 2023.2 重建 ABI 0E：TX=U20、RX=V15、禁发=W15、唯一 OBUFT；setup/hold 最差裕量分别为 **+0.249/+0.094 ns**，无失败端点。XSA 内嵌 bitstream 与独立文件 SHA256 一致；PetaLinux 2023.2 导入该 XSA，打包脚本核对 `system.bit` 与独立文件逐字节一致、rootfs 三套 CLI 与 UIO 模块/配置齐备、设备树包含 RTCS `generic-uio` 节点。`artifacts/sd/SHA256SUMS` 已校验通过。首次 Vivado 尝试因 setup −0.067 ns 被时序门禁拒绝，修正六轴反馈延时计数器的使能路径后重新综合才通过；失败尝试没有导出交付 bit/XSA。

| 文件 | SHA256 |
| --- | --- |
| [rtcs_system.bit](../artifacts/hw/rtcs_system.bit) | 0653954c619f330c8f54ecdd62f5966c8c0b420a7e8edb6e10163798ca678b22 |
| [rtcs_system.xsa](../artifacts/hw/rtcs_system.xsa) | 7811e2fd9a4fd2a78c7ca47955599c730e43d07e19154d24220cea2b0b344a72 |
| [BOOT.BIN](../artifacts/sd/BOOT.BIN) | 0168690f8999d1c9be03e9e44c3113c2168663b6ac108053828b6eefd14fe607 |
| [image.ub](../artifacts/sd/image.ub) | 1504b229dd41558d42603bf0ff5e1066f01b8a974ea9aa733c95a1a6fd5fc95c |
| [boot.scr](../artifacts/sd/boot.scr) | 81f427907b79f9120af4a9506ad9868af17044f13e1f3adee31906b8befb7441 |

复制三个 SD 文件到 FAT32 启动分区；复制前后按 [SHA256SUMS](../artifacts/sd/SHA256SUMS)核对。源码重建入口为 [Vivado 脚本](../scripts/build_vivado.ps1)的 Build/Ttl 选项，以及 [PetaLinux XSA 导入](../scripts/petalinux/create_project.sh)和 [SD 打包](../scripts/petalinux/build_sd_image.sh)。旧 ABI 镜像和 CLI 不混用。

## G3 首项：开机 UIO 与只读诊断

本次提供的[两条六轴广播日志](../artifacts/archive/g2-abi12-board-20261009/dual-sync-fault5.txt)均显示 `write_sent=1`，但发后 READ 的底层码 8 表示舵机应答的 ERROR 字节非零；不是六轴到位的软件通过记录。换用上表 SD 文件并重启后，**不执行手动 `modprobe`**，先核对：

    cat /sys/class/uio/uio0/name
    cat /sys/class/uio/uio0/maps/map0/addr
    cat /sys/class/uio/uio0/maps/map0/size
    ls -l /dev/uio0

预期依次为 `rtcs`、`0x43c00000`、`0x10000` 和存在的设备节点。任一不符则保存启动日志并停止，不直接开始运动。使物理允许跳线处于可 READ 状态，机械臂静止时执行：

    sudo rtcs-pl-g1 --uio /dev/uio0 probe
    sudo rtcs-pl-g2-six --uio /dev/uio0 limits
    sudo rtcs-pl-g2-six --uio /dev/uio0 diagnose
    sudo rtcs-pl-g2-six --uio /dev/uio0 torque-status --id 5

`diagnose` 不需要 `--execute`，只对 ID 1–6 发 READ_POSITION，不发运动 WRITE。保存六行 `diagnose id=` 和末行 `RTCS_PL_G2_SIX_DIAG`，同时保存 ID 5 扭矩开关只读值。六轴均正常时末行应为 `OK issues=0 read_only=1 write_sent=0`；任一舵机 ERROR 或 READ 故障时为 `INCOMPLETE` 并返回非零。特别记录 ID 2、5 的原始 `servo_error`。如有异常，停止 G3 运动准备，先排查后再次只读确认；不要从旧日志推断具体故障原因或自动重发旧目标。

只有操作者依据**当次** diagnose 和机械空间明确选择限位内的小幅六轴目标后，才做一次受控 `move-six`。保存每轴 target/last/target_error、有效位与 `command_result`；ABI 0E 显式绝对运动不采起点，start/actual_delta/position_change_mask 应为 `UNAVAILABLE`。若报 `engine_fault=8`，应保存 `fault_id`、`phase`、`servo_error_raw=0xNN`、`write_sent`；广播仍显示 `unicast_ack=NOT_APPLICABLE_BROADCAST`。任意 ERR、物理干涉或异常动作均停止后续提交；故障不会自动重发。

## 核心板端验收代码

1. **不装物理允许跳线**，运行只读命令，核对 ABI、禁发及六轴限位：

       sudo rtcs-pl-g1 --uio /dev/uio0 probe
       sudo rtcs-pl-g2-six --uio /dev/uio0 limits

   应有 id_version=0x5254000e、physical_tx=DISABLED、calibrated_mask=0x3f；逐轴 min/max/reference_count/speed_raw_max 必须与 [配置表](../config/g2_measured_limits.toml)一致。ID 5 的 0–4000 是操作者认可的命令范围，不是机械全行程实测边界；参考位置不是自动安全回位目标。

2. 清空工作空间、核对关节支撑与电源后，装上允许跳线并重新 probe，再只读清点：

       sudo rtcs-pl-g1 --uio /dev/uio0 probe
       sudo rtcs-pl-g2-six --uio /dev/uio0 diagnose

   应有 physical_tx=ENABLED 和六个唯一 ID 的本次实时位置。下面的尖括号是占位符，必须由操作者根据这次读数、机械空间和实测闭区间逐项替换，不能直接运行：

       sudo rtcs-pl-g2-six --uio /dev/uio0 move-six \
         --axis 1:<目标1>:500:10 --axis 2:<目标2>:500:10 \
         --axis 3:<目标3>:500:10 --axis 4:<目标4>:500:10 \
         --axis 5:<目标5>:500:10 --axis 6:<目标6>:500:10 \
         --observe-ms 5000 --execute

   默认容差为各轴 ±30 count，可用 --tolerance ID:N 在 1–100 count 内显式设置。核对 write_sent=1、unicast_ack=NOT_APPLICABLE_BROADCAST、fault=0、每轴有效 last/target_error 与连续稳定结果；start/actual_delta 为 `UNAVAILABLE`。重复提交前重新 diagnose。位置反馈到位也不等于实物抓取成功。

3. 越限拒绝测试仅在已完成正常同步写后进行。重新 diagnose，其余五轴填写当次位置，故意给 ID 2 写 860（实测下限 861）。应在发前报 ERR axis=2 target_or_speed_outside_pl_limit，不出现 commit 或动作。

       sudo rtcs-pl-g2-six --uio /dev/uio0 move-six \
         --axis 1:<本次位置1>:500:10 --axis 2:860:500:10 \
         --axis 3:<本次位置3>:500:10 --axis 4:<本次位置4>:500:10 \
         --axis 5:<本次位置5>:500:10 --axis 6:<本次位置6>:500:10 --execute

4. 软件停止测试由操作者在受控运动中执行，并记录请求到实际停止的延迟：

       sudo rtcs-pl-g2-six --uio /dev/uio0 stop --execute

   只有出现 RTCS_PL_G2_SIX_OK command=stop 才算软件停止成功。fault 5 必须看 fault_id、phase、engine_fault 和 write_sent，以区分保持广播前后的 READ 失败。独立断电急停另行在支撑受载关节的条件下实测，软件 stop 不能代替它。

任一 ABI/限位不符、ID 缺失、物理禁发状态异常、ERR、干涉或异常动作均停止后续提交并保留日志；故障不会自动重试。G2 阶段总结与核心文件目录见 [G2 说明](2.G2-six-axis-calibration.md)。历史多版本操作记录与旧镜像见 [artifacts/archive/](../artifacts/archive/)。
