# RTCS SD 启动与 G2 迭代

## 当前 ABI 12：逐命令故障与六轴板端验收

本节仅供操作者在烧录匹配的 ABI `0x5254000C` SD 文件后执行；上板运动不会由软件构建者代跑。当前三件套哈希见 [SHA256SUMS](../artifacts/sd/SHA256SUMS)，寄存器语义见 [ABI 12 契约](g2-abi12-registers.md)。接线仍为 J20-35/V15←BusLinker TX、J20-33/U20→BusLinker RX、J20-37↔GND；J20-36/W15↔J20-38/GND 为独立物理允许跳线。

2026-10-08 使用 Vivado 2023.2 `-Build -Ttl` 及 PetaLinux 2023.2 完整重建；2026-10-09 为两个 G2 CLI 的逐命令 fault 字段重建 rootfs 和 SD 三件套。引脚检查为 `tx=U20 rx=V15 inhibit=W15 pullup=TRUE obuft=1`；路由后 setup/hold 最差裕量为 `0.246/0.068 ns`，均无失败端点。XSA 内嵌 bitstream 与独立 `.bit` 的 SHA256 相同，PetaLinux 打包前还逐字节核对 `system.bit` 与独立 `.bit`；rootfs 包含 G1、G2 单轴和 G2 六轴 CLI。

| ABI 12 产物 | SHA256 |
| --- | --- |
| `artifacts/hw/rtcs_system.bit` | `e01578f5c448c40e61298d20d40073bfb8fd89b4d449bc5beb4a78ebca5c9971` |
| `artifacts/hw/rtcs_system.xsa` | `7eeb8f6e364342dc4244bb80572d30b7bb1a688c7c3f0c9d0336f6b61d0847ef` |
| `artifacts/sd/BOOT.BIN` | `29c49ec70aab6492ef06bb425b8cb31807ed5266ea0443b065079dd5c04b74f7` |
| `artifacts/sd/image.ub` | `55f89f7f7d2711b794f518ede8d2618ed18f0d8b070decb1fc3106c54ded7eef` |
| `artifacts/sd/boot.scr` | `11242ad17e37ff52e9c1da2d9b5a668dfb4f819c34134f9d61ceaab45e153c52` |

先**不装允许跳线**，依次执行只读诊断：

```sh
sudo rtcs-pl-g1 --uio /dev/uio0 probe
sudo rtcs-pl-g2-six --uio /dev/uio0 limits
```

应分别读到 `id_version=0x5254000c physical_tx=DISABLED`，以及 `abi=0x5254000c calibrated_mask=0x3f`、六轴 min/max/reference_count/speed_raw_max 与[实测配置](../config/g2_measured_limits.toml)一致。参考位置不是通用安全回位姿态。任一 ABI、掩码或限位不符即停，不运行运动命令。

确认线缆、关节支撑、独立电源和清空的机械空间后，操作者装上物理允许跳线，重新 `probe` 并只读清点：

```sh
sudo rtcs-pl-g2-six --uio /dev/uio0 inventory
```

应得到 ID 1–6 的**当次实时**位置，并以 `RTCS_PL_G2_SIX_INVENTORY_OK` 结束。首次 `move-six` 只选一轴朝实测范围内部的小幅目标，其余五轴显式填入本次读数；六个数都由操作者核对后代入，不能直接运行以下占位符：

```sh
sudo rtcs-pl-g2-six --uio /dev/uio0 move-six \
  --axis 1:<目标1>:500:10 --axis 2:<目标2>:500:10 \
  --axis 3:<目标3>:500:10 --axis 4:<目标4>:500:10 \
  --axis 5:<目标5>:500:10 --axis 6:<目标6>:500:10 \
  --observe-ms 5000 --execute
```

逐轴默认到位容差为 ±30 count；如已有对应速度的实测误差依据，可显式加 `--tolerance ID:N`（`1–100`）分别指定。输出应含本次 `write_sent=1`、`unicast_ack=NOT_APPLICABLE_BROADCAST`、`fault=0 fault_id=0`、每轴 `start/target/last/actual_delta/target_error` 和 `RTCS_PL_G2_SIX_OK command=move-six`。位置读数变化与到位带判定分别核对；目标等于起点的轴允许 `actual_delta=0`，不能宣称该轴发生运动。每次重复同步运动都先重新清点现场位置、明确六个新目标，再单独提交一次。

验证越限拒绝时，先完成上述正常命令并重新只读清点，用本次六个实时位置填入以下其余五轴；ID 2 的 `860` 故意低于实测下限 `861`。应出现 `ERR axis=2 target_or_speed_outside_pl_limit`，且没有 `commit` 或 WRITE；若出现提交或任何动作，立即停止测试。

```sh
sudo rtcs-pl-g2-six --uio /dev/uio0 move-six \
  --axis 1:<本次位置1>:500:10 --axis 2:860:500:10 \
  --axis 3:<本次位置3>:500:10 --axis 4:<本次位置4>:500:10 \
  --axis 5:<本次位置5>:500:10 --axis 6:<本次位置6>:500:10 --execute
```

遇任一 ID 缺失、现场位置越限、物理禁发与预期不符、任意 `ERR`、fault 9/16、异常动作或干涉，应停止后续提交并保存完整日志。故障不再永久闭锁，排障后也只由操作者重新明确提交，不自动重试。总线仍可通信且需要保持现场姿态时可运行 `sudo rtcs-pl-g2-six --uio /dev/uio0 stop --execute`；只有出现 `RTCS_PL_G2_SIX_OK command=stop` 才说明软件停止完成。fault 5 的输出必须核对 `fault_id`、`phase=pre_write_read` 或 `phase=post_write_feedback`、`write_sent` 和底层 `engine_fault`，不可把“已请求 stop”误读为成功。独立断电急停按受载关节支撑要求进行实测，软件 stop 不能代替它。

完成标准：保留首次与重复 `SYNC WRITE` 的实际反馈、逐轴限位拒绝、软件停止延迟以及独立断电急停记录。单次“六轴都动了”不足以完成 G2。

## ABI 11 历史操作入口

此节记录当时 ABI `0x5254000B` 的构建和操作方式，已经由上面的 ABI 12 流程取代。旧 ABI 11 的 bitstream、XSA、SD 三件套与哈希已在[归档](../artifacts/archive/g2-six-abi11-pre-abi12-20261008/README.md)；不同 ABI 的 CLI、bitstream 与镜像不能混用。六轴安装状态的实测限位及当时称作“回零”的参考位置见 [ABI 11 契约](g2-abi11-registers.md)。`1000 count` 约对应 `90°` 的舵机标定值不构成关节角度 API；各关节方向尚未提供。

2026-10-08 Vivado `-Build -Ttl` 和 PetaLinux 2023.2 构建成功。引脚检查为 `tx=U20 rx=V15 inhibit=W15 pullup=TRUE obuft=1`；路由后 setup/hold 最差裕量分别为 `0.415/0.041 ns`，无失败端点。XSA 内嵌、独立 `.bit`、PetaLinux `system.bit` 的哈希一致；rootfs 中核对到 `rtcs-pl-g2-six` 及 `limits` 命令。

| ABI 11 产物 | SHA256 |
| --- | --- |
| `artifacts/hw/rtcs_system.bit` | `7a2b5f9232d63261de66daa5cb8578b9aa5d2d8f139745be398a73534abef7de` |
| `artifacts/hw/rtcs_system.xsa` | `b124d56cf74b44c4348a5f51e1056c2a1668bd7aa54615d50ecc6274c3d7fa4d` |
| `artifacts/sd/BOOT.BIN` | `5acfde6dfe870bb13f7ab4a17fb62741461641f88e1d381d29c5f3df89674ccf` |
| `artifacts/sd/image.ub` | `626b2d9c2c1936fb26cc7209e93f8b71d780c7bb4bd8b7e464472b2d9980e632` |
| `artifacts/sd/boot.scr` | `835b509ffa6180f250dff13b9f7fb70e6d03e5f12037292b583bf2dec054b8cc` |

接线：J20-35/V15←BusLinker TX、J20-33/U20→BusLinker RX、J20-37↔GND；J20-36/W15↔J20-38/GND 是独立物理发送允许跳线。先不装允许跳线，只读核对：

```sh
sudo rtcs-pl-g1 --uio /dev/uio0 probe
sudo rtcs-pl-g2-six --uio /dev/uio0 limits
```

`probe` 须显示 `id_version=0x5254000b`、`physical_tx=DISABLED`。`limits` 须显示 `abi=0x5254000b calibrated_mask=0x3f`、六轴 `min/max/home/speed_raw_max` 与实测表逐项一致，最后为 `RTCS_PL_G2_SIX_LIMITS_OK calibrated_mask=0x3f`。应读到：ID 1 `1000/3000/2000/1500`，ID 2 `861/1500/861/1500`，ID 3 `2000/3117/3117/1500`，ID 4 `2000/2861/2861/1500`，ID 5 `0/4000/2000/1500`，ID 6 `1585/2500/1585/1500`，每组依次为最小、最大、回零、原始速度上限。

检查接线、供电、关节支撑和机械空间后，由操作者安装允许跳线，再执行只读现场清点：

```sh
sudo rtcs-pl-g2-six --uio /dev/uio0 inventory
```

应有六个唯一 ID 的**本次实时** `position_raw`，末行 `RTCS_PL_G2_SIX_INVENTORY_OK ids=1,2,3,4,5,6`。任何一个当前位置超出其 PL 限位、`fault_latched=1`、读数异常或总线错误时停止运动排查。故障锁只在排查后复位 PL 才清除；`stop` 不清锁。

首次同步试动由操作者依据这次 `inventory` 填写六个显式轴参数：选一个轴向限位内部移动一个经机械空间检查的小幅目标，其余五轴以各自本次读数为目标；全部目标均在对应闭区间。推荐原始速度 `500`，时间原始字段 `10`。命令形态为：

```sh
sudo rtcs-pl-g2-six --uio /dev/uio0 move-six --axis 1:<本次目标1>:500:10 --axis 2:<本次目标2>:500:10 --axis 3:<本次目标3>:500:10 --axis 4:<本次目标4>:500:10 --axis 5:<本次目标5>:500:10 --axis 6:<本次目标6>:500:10 --execute
```

不要原样运行带占位符的命令，也不要把回零表或旧日志当作实时位置。每次显式提交仅发送一帧，失败后不会自动重发。板端需记录首次和重复 `SYNC WRITE`、每轴反馈、越限拒绝、软件停止延迟及独立断电急停测试；这些实物记录齐全前，G2 不标为完成。总线仍可通信且需要保持现场姿态时，可执行 `sudo rtcs-pl-g2-six --uio /dev/uio0 stop --execute`；软件 `stop` 不是紧急停止。

遇 ABI 或限位不符、物理禁发状态与预期不符、ID 缺失、故障锁、任意 `ERR`、fault 9、5 秒观察期超时、异常运动或机械干涉，停止后续运动命令并保存日志；必要时使用独立断电急停。所有速度和时间值均是协议原始字段。

## ABI 10 历史操作入口

ABI 10 当时的源码和产物为 `0x5254000A`。2026-10-08 用当时 RTL 执行 Vivado `-Build -Ttl`，导入 XSA 后完成 PetaLinux 构建，三件套哈希校验通过。旧 ABI 09 的文件与实物摘要在[归档](../artifacts/archive/g2-six-abi09-board-20261008/README.md)。本节及以下 ABI 09 和更早命令、哈希只作历史记录；不得混用不同 ABI 的 CLI、bitstream 与 SD 文件。接口细节见 [ABI 10 契约](g2-abi10-registers.md)。

本次 Vivado 检查：`tx=U20 rx=V15 inhibit=W15 pullup=TRUE obuft=1`；路由后 setup 最差裕量 `0.207 ns`、hold 最差裕量 `0.020 ns`，均无失败端点。XSA 内嵌 bitstream、独立 `.bit` 和 PetaLinux `images/linux/system.bit` 一致；rootfs 清单包含 `rtcs-pl-g1`、`rtcs-pl-g2`。`BOOT.BIN` 由本次 FSBL、bitstream、U-Boot 和设备树打包，`image.ub` 由同一次构建生成。实体 SD 更新和实物复测仍由操作者执行。

| ABI 10 产物 | SHA256 |
| --- | --- |
| `artifacts/hw/rtcs_system.bit` | `3485c613a8da90ba3947aaf8760064f0326b461ccc7ac011c47cb2e4496430b3` |
| `artifacts/hw/rtcs_system.xsa` | `91ec13faa82e7796151c2a8e04e32da791491250bbe4e0a57c2e485197d1440e` |
| `artifacts/sd/BOOT.BIN` | `1cf4a3824229bcfa92d3d516174db7a5ae0a1975aa0be88e8844433b5ba6a959` |
| `artifacts/sd/image.ub` | `a5ece573e0fc9f378c3c016f776d21796fce9dba24f25c13c834bf808997ba66` |
| `artifacts/sd/boot.scr` | `bf8a17bbb9bb3b804c8b7481a8682fd8135fb5d114a06f9e09180beb395b7150` |

SD 三件套的当前校验文件为 [SHA256SUMS](../artifacts/sd/SHA256SUMS)。

接线仍为 J20-35/V15←BusLinker TX、J20-33/U20→BusLinker RX、J20-37↔GND，J20-36/W15↔J20-38/GND 为单独物理允许跳线。首先在无允许跳线下运行 `probe`，必须看到 `id_version=0x5254000a` 和 `physical_tx=DISABLED`；若不符即停。允许物理 TX 后，用户在板端依次执行只读命令：

```sh
sudo rtcs-pl-g1 --uio /dev/uio0 probe
sudo rtcs-pl-g2-six --uio /dev/uio0 inventory
sudo rtcs-pl-g2-six --uio /dev/uio0 torque-status --id 2
```

`inventory` 应有六个唯一 ID 和实时位置；`torque-status` 应输出 `RTCS_PL_G2_SIX_TORQUE id=2 register=0x28 value=...`。读取值仅说明 SRAM 状态，不说明已经运动。若决定继续，逐轴标定命令示例为 `sudo rtcs-pl-g2-six --uio /dev/uio0 calibrate-step --id 2 --delta 20 --execute`。应记录 `calibrate-start`、逐条 `sample=`、`calibrate-final`、`write_ack` 和最终 `RTCS_PL_G2_SIX_OK`；只有连续三次目标 ±5 count 才会报 OK。`fault=9` 表示 WRITE 后 5 秒未确认到位，应保存全部日志检查负载、线缆和扭矩读数，不把 WRITE 应答当作运动成功。

单轴绝对目标由操作者在**本次** inventory 和机械空间检查后决定；格式为 `sudo rtcs-pl-g2 --uio /dev/uio0 move --id 2 --target 目标原始count --speed-raw 1500 --time-raw 10 --execute`，其中 `1500/10` 仅为已使用过的协议原始字段。ID 2–6 的此路径允许任何 16 位目标，PL 没有这些关节的实测安全限位；不要把旧位置或舵机标称 4000 count 当作机械限位。遇 ABI 不符、物理禁发、任意 `ERR`、`AFTER_2S`、位置读数异常或机械干涉即停止后续提交；必要时在总线仍可通信时运行 `sudo rtcs-pl-g2-six --uio /dev/uio0 stop --execute`，并使用独立电源急停。`stop` 不清故障锁，也不代替断电急停。当前 `calibrated_mask=0x00`，六轴 `move-six` 仍应报未标定拒绝，不发送广播 WRITE。

