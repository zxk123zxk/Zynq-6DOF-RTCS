# RTCS：SD 启动、Linux 验证与后续迭代操作说明

现行自动化入口如下。新 XSA 已完成 Vivado 实现和导出；是否能在实物上 SD 启动仍须重新验收。

- Windows 新硬件：`powershell -ExecutionPolicy Bypass -File scripts/build_vivado.ps1 -Build`
- WSL 导入新 XSA：`bash scripts/petalinux/create_project.sh --import-hw "$PLNX_PROJECT"`
- WSL 仅更新 Linux 应用/设备树：`bash scripts/petalinux/create_project.sh --sync-only "$PLNX_PROJECT"`
- WSL 增量构建并打包：`bash scripts/petalinux/build_sd_image.sh "$PLNX_PROJECT"`

唯一硬件平台为 `artifacts/hw/rtcs_system.xsa`；报告在 `artifacts/reports/`，SD 文件在 `artifacts/sd/`，日志在 `artifacts/logs/`。不需要删除现有 PetaLinux 项目或 sstate 缓存。

## 0. 当前产物已经具备什么

本次脚本的输出目录是仓库 `artifacts/sd/`，其中应有以下文件：

| 文件 | 作用 |
| --- | --- |
| `BOOT.BIN` | Zynq 上电时由 BootROM 从 SD 卡加载。当前包内含 FSBL、PL bitstream 和 U-Boot。 |
| `image.ub` | U-Boot 加载的 Linux 内核、设备树和本项目当前使用的 initramfs 根文件系统镜像。 |
| `boot.scr` | U-Boot 脚本：从 `mmc 0:1` 的 FAT 分区读取 `image.ub`，然后启动。166 B 是正常大小。 |
| `SHA256SUMS` | 三个启动文件的 SHA-256 校验表。 |

文件存在与校验通过不证明 FSBL/DDR 已在实物通过；必须以新 XSA 打包后上板复验。TFTP 警告不影响 SD 启动。

可在 WSL 中校验输出文件是否被意外改坏：

```bash
cd /mnt/d/3.Electronic_Information/2026.9-ES_Competition-FPGA-AMD/Zynq-6DOF-RTCS/artifacts/sd && sha256sum -c SHA256SUMS
```

预期每一行均为 `OK`。

## 1. “第一个 FAT32 分区”究竟是什么

它不是开发板上的某个目录，也不是把四个文件烧进 FPGA 的操作。它是 **microSD 卡的第 1 个分区**：

```text
microSD 卡
├─ 分区 1：FAT32，卷标可设为 BOOT
│  ├─ BOOT.BIN
│  ├─ image.ub
│  └─ boot.scr
└─ （本项目当前不需要第 2 个 ext4 分区）
```

当前 [`boot.cmd`](../scripts/petalinux/boot.cmd) 明确使用 `fatload mmc 0:1`，其中 `0:1` 的 `1` 就是“第一个分区”。所以这三个文件必须直接放在该 FAT32 分区的根目录，不能放入 `sd/`、`boot/` 等子目录。

这个工程目前的 `image.ub` 含有启动所需的 initramfs，因此不必额外创建 ext4 根文件系统分区。以后若改成从 `rootfs.ext4` 启动，才需要另行设计第二分区和更改启动脚本。

### 在 Windows 上准备卡

1. 关机后取出 microSD；先备份卡中内容。
2. 在开始菜单运行 `磁盘管理`（`diskmgmt.msc`），**按容量核对**哪一块是 microSD 卡，绝不要按盘符猜测。
3. 删除该卡原有卷，创建一个“简单卷”，占满全卡，格式选择 FAT32；使其成为第一个分区。
4. 如果卡大于 32 GB，Windows 自带格式化界面可能不提供 FAT32。此时可使用 Linux 的 FAT32 格式化工具或可信的 FAT32 格式化工具；不要将卡格式化成 exFAT/NTFS。
5. 打开这个 FAT32 卷，将仓库 `artifacts/sd/` 中的 `BOOT.BIN`、`image.ub`、`boot.scr` 复制到卷根目录。`SHA256SUMS` 可以一同保留，但启动不依赖它。
6. 使用“安全删除硬件”弹出读卡器，再插入 AX7Z020B 的 Micro SD 卡座。

对含有数据的磁盘进行删除/格式化是不可逆操作；执行前必须再次核对容量、型号和盘符。当前目录给出的是一组可复制的启动文件，而不是可被 Balena Etcher 直接写入的 `.img` 整盘镜像。

## 2. AX7Z020B 如何切换到 SD 启动

从你提供的板卡照片可见，电池旁的两位拨码开关 `SW1` 印有启动模式表：

| 启动源 | SW1-1 | SW1-2 |
| --- | --- | --- |
| JTAG | ON | ON |
| QSPI | OFF | ON |
| SD | **OFF** | **OFF** |

操作顺序：

1. 断开开发板电源；不要在上电状态切换启动拨码。
2. 将 `SW1` 的 1、2 两位都拨到丝印标注的 **OFF** 一侧。
3. 插入已经准备好的 microSD 卡。
4. 将 PC 用 Mini-USB 线连接开发板标有 `UART` 的口（这是 CP2102 调试串口），再给开发板正常供电。
5. 上电。Zynq 会从 SD 卡读 `BOOT.BIN`，不需要在 Vivado 中再点“Program Device”。

SD 启动不是把镜像写入开发板的易失配置存储器：镜像留在 SD 卡上，板子每次上电都从卡读它。今后更新镜像的通常流程就是关机、取卡、在 PC 上覆盖这三个文件、插回卡并上电。

`JTAG` 仍可用于 Vivado 的临时下载、ILA 调试或 XSCT 调试，但它不是本项目运行 Linux 的常规启动路径。不要把机械臂 BusLinker 的 JTAG/TTL 插针当成 Zynq 的启动接口。

## 3. 不启用 smoke 时，怎样确认 Linux、PS UART 与 USB 串口成功

`rtcs-uart-smoke` 只是一个“PC 通过 CP2102 发送整数、Linux 回显整数+1”的演示程序。它没有参与 SD 引导，也不验证 BusLinker 或舵机。不勾选它不会影响 PS UART 控制台、SD 启动、USB Host 或 `rtcs-buslinker-g1`。

### 3.1 先确认 Linux 与 PS UART 控制台

Windows 打开串口终端（MobaXterm、PuTTY 等），选择开发板 `UART` 口对应的 COM 号，配置为 **115200、8N1、无流控**。上电后应先看到 FSBL/U-Boot，再看到 Linux 内核和登录提示。进入系统后执行：

```sh
uname -a
```

能在 PC 串口上看到 Linux 内核版本并能接受命令，即证明：SD 启动、PS DDR、Linux 内核、设备树和 PS UART 控制台这一链路正常。

### 3.2 再确认 USB Host 与 BusLinker 串口

硬件应保持如下连接：

```text
AX7Z020B 的 USB HOST Type-A ── USB 线 ── BusLinker V3.0 Type-C
BusLinker 独立 5–14 V 供电 ── 舵机总线
```

BusLinker 需要独立供电；不要指望开发板 USB Host 给机械臂/多个舵机供电。BusLinker 跳帽应保持此前确认的 `Servo–USB` 模式。

插入 BusLinker 后在开发板 Linux 控制台运行：

```sh
dmesg | grep -Ei '1a86|55d3|cdc_acm|ch341|ttyACM|ttyUSB'
```

以及：

```sh
ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
```

已确认的 BusLinker V3.0 枚举为 `1a86:55d3`：应检查 `cdc_acm` 绑定和 `/dev/ttyACM<N>`。旧 CH341 设备才检查 `ch341` 绑定和 `/dev/ttyUSB<N>`；序号以实际输出为准。

若已有 `1a86:55d3` 枚举却没有 `/dev/ttyACM<N>`，检查运行内核是否有 `CONFIG_USB_ACM=y` 及 `cdc_acm` 绑定；本工程也保留 `CONFIG_USB_SERIAL_CH341=y` 兼容旧设备。不要把枚举成功当作串口节点已建立。

### 3.3 最后进行只读 G1 通信验证

先检查 G1 应用是否实际进入了根文件系统：

```sh
command -v rtcs-buslinker-g1
```

若得到 `/usr/bin/rtcs-buslinker-g1`，且用户明确确认了舵机的单播 ID，才执行只读命令；`<ID>` 不得默认取 1：

```sh
rtcs-buslinker-g1 --device /dev/ttyACM<N> --id <ID> ping
```

预期末行是 `RTCS_BUSLINKER_G1_OK`。该程序只发送单播 `PING` 或读取当前位置，不会发送位置、速度、扭矩、广播或复位写命令，因此不会让舵机运动。读取位置可用：

```sh
rtcs-buslinker-g1 --device /dev/ttyACM<N> --id <ID> read-position
```

旧 CH341 路径则替换为实际的 `/dev/ttyUSB<N>`。若命令不存在，检查 `rootfs_config` 中 `CONFIG_rtcs-buslinker-g1=y`。只读验收脚本用法为 `rtcs-g1-readonly-check <设备路径> <ID> <日志目录>`；日志目录必须可写且日志可回收至仓库 `artifacts/logs/`。未挂载时可用串口终端保存输出。

## 4. 下次修改代码后，哪些步骤必须重做

不要删除旧 PetaLinux 项目、`build/` 或下载缓存来“重新开始”。PetaLinux/BitBake 的 sstate 缓存能复用大量任务；删除它只会让构建明显变慢。应按改动类型决定最短路径。

| 改动内容 | 是否需要新 XSA | 最短后续步骤 |
| --- | --- | --- |
| 仅 Linux 用户程序、rootfs 包选择、内核配置 | 否 | 更新 PetaLinux 项目里的对应 recipe/文件或配置，然后 `petalinux-build`，再运行 SD 打包脚本。 |
| 仅 PL 的 SV、HLS、BD、时钟、AXI 地址或 PS 硬件配置 | 是 | Vivado 重新实现并导出 XSA；将新 XSA 导入**现有** PetaLinux 项目；再构建、打包 SD。 |
| 新增/更改设备树节点 | 通常否（除非硬件地址也改） | 更新 device-tree recipe，重新 `petalinux-build` 和 SD 打包。 |
| 仅替换 SD 上的三个启动文件 | 否 | 关机，覆盖 FAT32 根目录中的 `BOOT.BIN`、`image.ub`、`boot.scr`，再上电。 |

硬件改动时运行本文件开头的 Windows 构建、`--import-hw` 和 SD 打包三条命令；仅 Linux/设备树改动时运行 `--sync-only` 和 SD 打包。导入操作在现有 PetaLinux 项目内增量执行，保留用户在 `rootfs_config` 中的包选择。

## 5. 本项目当前的安全边界

当前可启动镜像对应 G0/G1 验证路径：PL 中 `servo_tx_en` 仍被固定关闭；`rtcs-buslinker-g1` 只进行单播 PING/位置读取。即便 SD 启动、USB 枚举和 G1 PING 全部成功，也不等于“PL 已经直驱六轴机械臂”。这正是合适的阶段性验收：先证明 PS/Linux/USB/协议读通，再单独设计并验证 PL 的电平转换、半双工收发和运动写帧。

