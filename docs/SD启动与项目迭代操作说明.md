# 当前 SD 镜像与板端命令

本页记录的**仓库 SD 镜像**于 2026-10-13 重建，ABI 为 `0x5254000E`，ID 6 PL 命令限位为 2050–3000，参考读值为 2092。**板端最后一次 `limits` 仍读出旧限位 1585–2500、reference 1585**；新镜像尚未上板验收。同一 ABI 不能区分两版限位，必须核对逐轴 `limits`。绝对目标不要求发前 READ 成功，0D 旧版不可混用。旧版 ABI 0E 镜像见[本次归档](../artifacts/archive/g3-id6-old-limits-abi0e-20261013/README.md)。J20-35/V15 接 BusLinker TX，J20-33/U20 接 BusLinker RX，J20-37 共地；J20-36/W15 到 J20-38/GND 是物理允许跳线。独立舵机电源开关与该跳线分开。所有舵机运动只由板端操作者执行。

## 交付文件

2026-10-13 用 Vivado 2023.2 重建 ABI 0E：TX=U20、RX=V15、禁发=W15、唯一 OBUFT；setup/hold 最差裕量分别为 **+0.499/+0.042 ns**，无失败端点。PetaLinux 2023.2 导入新 XSA，打包脚本核对 `system.bit` 与独立 bitstream 逐字节一致、rootfs 三套 CLI 与 UIO 模块/配置齐备、设备树包含 RTCS `generic-uio` 节点。`artifacts/sd/SHA256SUMS` 已校验通过。旧镜像及其哈希见[归档](../artifacts/archive/g3-id6-old-limits-abi0e-20261013/README.md)。

| 文件 | SHA256 |
| --- | --- |
| [rtcs_system.bit](../artifacts/hw/rtcs_system.bit) | 3f198ff2ed30b65b4e0686b005a8f92c7f4af3d35164a16c790ea9a91698d6a7 |
| [rtcs_system.xsa](../artifacts/hw/rtcs_system.xsa) | b096eb32eada36d33ee7b2897678ce3dc28a65dd2a6ca66a3cd3d63b7fe8e38a |
| [BOOT.BIN](../artifacts/sd/BOOT.BIN) | c03cbf619b2d9c1eb4886fb4922fc4ce28b20ed0bcb8e289abd2b28e79645836 |
| [image.ub](../artifacts/sd/image.ub) | f0274a0bfdcc40669e88ceba21dfc93d78969f37448453b8c7e4c41700c4b16a |
| [boot.scr](../artifacts/sd/boot.scr) | a05b62f308bf0f5685aeebaec0f17f323dbaa7b668b2327abfa159ce1ffc8c49 |

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

`diagnose` 不需要 `--execute`，只对 ID 1–6 发 READ_POSITION，不发运动 WRITE。保存六行 `diagnose id=` 和末行 `RTCS_PL_G2_SIX_DIAG`，同时保存 ID 5 扭矩开关只读值。六轴均正常时末行应为 `OK issues=0 read_only=1 write_sent=0`；任一舵机 ERROR 或 READ 故障时为 `INCOMPLETE` 并返回非零。原始 `servo_error` 用于诊断当次 READ；它不锁死下一条显式运动命令，也不要求先重复诊断才可继续。

操作者可依据机械空间选择限位内的六轴目标并执行 `move-six`，不要求发前 READ 起点。保存每轴 target/last/target_error、有效位与 `command_result`；ABI 0E 显式绝对运动的 start/actual_delta/position_change_mask 为 `UNAVAILABLE`。若报 `engine_fault=8`，保存 `fault_id`、`phase`、`servo_error_raw=0xNN`、`write_sent`；广播仍显示 `unicast_ack=NOT_APPLICABLE_BROADCAST`。ERR 属于当次命令，不禁止后续显式提交；实际物理干涉或失控时使用独立急停。

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

ABI/限位不符时先选用正确镜像；当次 ERR 原样报告，不转成 OK，也不设跨命令锁死。实际机械干涉、失控或供电异常由操作者使用独立急停。G2 阶段总结与核心文件目录见 [G2 说明](2.G2-six-axis-calibration.md)。历史多版本操作记录与旧镜像见 [artifacts/archive/](../artifacts/archive/)。
