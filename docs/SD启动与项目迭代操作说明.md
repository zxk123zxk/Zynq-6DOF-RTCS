# RTCS：SD 启动与项目迭代操作说明

## 0. 当前版本

**旧镜像的 PL 直连 G1 已通过**：ID 1 单播 PING、当前位置 READ（`position_raw=2038`）及断开该舵机总线后的 PING/READ 超时均已由用户上板确认，旧镜像和哈希保存在 [`artifacts/archive/g1-u20-inhibit-abi02-20261005/`](../artifacts/archive/g1-u20-inhibit-abi02-20261005/MANIFEST.md)。当时没有仪器测得的 Bank34 VCCIO、BusLinker TTL 空闲电压，也没有独立电源开关切断效果的实测记录；这些缺项不撤销 G1 只读功能通过结论，但不构成 G2 实物运动许可。

本版将接线迁移为 J20-33/U20 RX、J20-35/V15 TX、J20-37 GND、J20-36/W15 禁发输入。**仅 J20-36↔J20-38/GND 跳线接入时允许 PL 只读发帧**；不接跳线时 W15 上拉、TX 高阻。发送中拔掉跳线会中止事务，不自动续发。新 PL ABI 是 `0x52540003`；旧 `0x52540002` 镜像/应用及旧接线不可与新版混用。新镜像首次上板只验证不接 BusLinker 的 `probe`，不发舵机指令。

`artifacts/hw/` 为 Vivado 的 bitstream/XSA，`artifacts/sd/` 为 PetaLinux 的 `BOOT.BIN`、`image.ub`、`boot.scr` 与 `SHA256SUMS`。前三项复制到 SD；校验表仅供核对。每次重建后按第 1 节验证哈希。本仓库构建成功不等于已上板验收。

本版 Vivado 2023.2 实现 DRC 0 错误，内部时序 WNS `3.865 ns`、WHS `0.049 ns`；IO 报告确认 Bank34/LVCMOS33、U20=RX、V15=`TRISTATE`、W15=`PULLUP` 禁发输入，网表只有一个 `OBUFT`。板外异步 IO 仍有 3 条 `TIMING-18`，不能把内部时序收敛当成新接线的实物验收。构建和校验完成，但**新镜像尚未上板**。

新 `artifacts/sd/` SHA256：`BOOT.BIN` `96887c83997f0d6c5a92a09803ba67945b9a304474c6dd08ab33cc6f3f0ae628`；`image.ub` `a2cd32499ca78cb2de5db2425c809bec767c4ee071cc463799da132b462f4cfd`；`boot.scr` `a159345a5577cdeaba6fcc1738a324545cd56f4deb8c66570874630afb1b3f79`。`SHA256SUMS` 是校验表，不复制到 SD 也可。

## 1. 构建或迭代镜像（WSL/PetaLinux 命令）

以下命令在仓库根目录的 PowerShell 执行，用于 RTL/BD/PS 硬件变更；仅 Linux 程序或设备树变更可跳过 Vivado：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_vivado.ps1 -Build -Ttl
wsl -d Ubuntu-22.04
```

进入 WSL 后执行；沿用现有项目，**不要删除 PetaLinux 项目或 BitBake 缓存**：

```bash
source /home/zxkzxk/tools/petalinux/2023.2/settings.sh
cd /mnt/d/3.Electronic_Information/2026.9-ES_Competition-FPGA-AMD/Zynq-6DOF-RTCS
export PLNX_PROJECT=/home/zxkzxk/projects/zynq/petalinux-rtcs
bash scripts/petalinux/create_project.sh --import-hw "$PLNX_PROJECT"
bash scripts/petalinux/build_sd_image.sh "$PLNX_PROJECT"
cd artifacts/sd
sha256sum -c SHA256SUMS
```

若**只改 Linux 应用、recipe、设备树或内核配置**，在同样的 `source`、`cd` 和 `export` 后改用下列两条，不重新导出 XSA：

```bash
bash scripts/petalinux/create_project.sh --sync-only "$PLNX_PROJECT"
bash scripts/petalinux/build_sd_image.sh "$PLNX_PROJECT"
```

构建脚本会核实最终内核 `.config` 中的 `CONFIG_USB_ACM=y` 与 CH341 支持，并生成三文件及 `SHA256SUMS`；校验预期三行均为 `OK`。每次改变 PL 后必须先新 XSA、再 `--import-hw`、最后重新打包 SD，不能只替换 `.bit`。若要回到没有任何 PL 舵机端口的安全版，Vivado 命令去掉 `-Ttl` 并同样重建镜像。

## 2. 复制到 microSD 并验证启动

只把 `BOOT.BIN`、`image.ub`、`boot.scr` 复制到 microSD **第 1 个 FAT32 分区的根目录**；当前 `image.ub` 内含 initramfs，无需 ext4 分区。不要把整个 `artifacts/sd/` 当 `.img` 烧录，也无需重格式化一张已经是 FAT32 且可用的卡。若确需分区或格式化，先按容量和设备型号核对并备份；本说明不自动操作实体 SD。

断电后将 AX7Z020B 的 `SW1-1`、`SW1-2` 均拨到丝印 `OFF`（SD 启动），插卡。PC 接开发板独立的 CP2102 `UART` 调试口，串口终端设 **115200、8N1、无流控**，再以原装 5 V 给开发板供电。应看到 FSBL、U-Boot、Linux 和登录提示；此过程不需要 Vivado 再下载 bitstream。后续更新镜像只需关机、取卡、覆盖上述三文件、弹出卡、插回并上电。

## 3. Linux 启动与 UIO 核对

登录后在 Zynq 的 PS UART 控制台执行：

```sh
uname -a
command -v rtcs-pl-g1
for u in /sys/class/uio/uio*; do
    echo "$u"
    cat "$u/name" "$u/maps/map0/addr" "$u/maps/map0/size"
done
```

若没有 `/sys/class/uio/uio*`，先加载项目的 generic-uio 驱动再重查；使用 root 登录时可去掉 `sudo`：

```sh
sudo modprobe -r uio_pdrv_genirq 2>/dev/null || true
sudo modprobe uio_pdrv_genirq of_id=generic-uio
```

找到映射地址 `0x43c00000`、范围 `0x10000` 对应的 `/dev/uioN`，不要假定编号始终为 0；以下以 `/dev/uio0` 为例：

```sh
rtcs-pl-g1 --uio /dev/uio0 probe
```

新镜像下，**不装 J20-36↔J20-38 允许跳线**时应显示 `id_version=0x52540003`、`physical_tx=DISABLED`。按第 5 节断电装跳线并重启后应显示 `physical_tx=ENABLED`。若版本、UIO 地址/大小或状态不符，立即停止，勿发命令。PS UART1 控制台与 PL TTL 是两条不同链路。

## 4. 新针位接线表（本轮暂不接 BusLinker）

J20 是板边带护框的 2×20 公针，BusLinker 的 TTL 排针也是公针。用三根 2.54 mm 母对母杜邦线连接两板；另外用一根母对母线作 J20 上的本地允许跳线。以 [板卡照片](resource_file/AX7Z020B.JPG) 正面、J20 位于下边且电源插口在右为准：右端为 `1/2`、左端为 `39/40`；`35/36` 是从左数第 3 对，`37/38` 是第 2 对，`33/34` 是第 4 对。上排奇数、下排偶数；断电时复核板上丝印。


| AX7Z020B J20 | PL 功能 | BusLinker TTL 排针 |
| --- | --- | --- |
| 33 / U20 | RX 输入 | TX |
| 35 / V15 | 三态 TX 输出 | RX |
| 37 | 共地 | GND |

**第四根线只在 J20 内部：J20-36 / W15 / Bank34 ↔ J20-38 / GND。**不接它时 PL TX 被上拉禁止；发送时拆掉会立即停止物理发送并清空当前事务。不要把这根线接到 BusLinker 电源或信号排针。

**不要将 J20-39/40（+3.3 V）或 J20-2（+5 V）接到 BusLinker TTL。**断电后把 BusLinker 的两只跳帽都置于 `Servo–TTL`，舵机使用其独立 5–14 V 电源与开关。PL 直连时 BusLinker Type-C 不接 Zynq USB Host；Zynq 的 CP2102 `UART` 调试口仍接 PC。

电平依据：[AX7Z020B 手册](resource_file/AX7Z020B开发板用户手册.pdf)给出 Bank34 默认 3.3 V；[BusLinker V3.0 原理图](resource_file/BusLinker_v3.0.pdf) 的 J1/J8→`LOGIC_RX` 路径由 +3.3 V 供电的 U5（74LVC1G125）驱动，`LOGIC_TX` 由 +3.3 V 供电的 U4（74LVC1G126）驱动到舵机侧，后者另有 3.3 V 钳位。用户确认有独立舵机电源开关，但上述电压及开关切断效果没有本仓库实测记录，不写作已测值。新镜像首次上板按第 5 节保持 BusLinker 和舵机断开。

## 5. 新镜像首次上板：仅无 BusLinker `probe`

1. 关闭 AX7Z020B 和舵机电源；拆掉旧的 J20-33↔38 跳线以及所有连接 BusLinker TTL 的线。**此次不连接 BusLinker，也不给舵机供电。**确认 J20-36↔38 暂不连接。
2. 在电脑上核对 `artifacts/sd/SHA256SUMS`，将本次构建的 `BOOT.BIN`、`image.ub`、`boot.scr` 复制到 microSD 第 1 个 FAT32 分区根目录，安全弹出。不得混入旧版三个文件；本助手不操作实体 SD。
3. SD 启动并登录，按第 3 节确认 UIO 名称为 `rtcs`、地址 `0x43c00000`、大小 `0x10000`。执行 `rtcs-pl-g1 --uio /dev/uioN probe`，预期 `id_version=0x52540003` 且 `physical_tx=DISABLED`。
4. 关机并断电后，只把 J20-36/W15 接到 J20-38/GND，**仍不连接 BusLinker**。重新上电、登录并再次执行同一个 `probe`；预期同一 ABI 且 `physical_tx=ENABLED`。这里的 `ENABLED` 仅表示允许条件满足；`probe` 不启动 UART 发送。
5. 记录两次控制台输出和所复制文件的 SHA256。测试结束先断电，再取下跳线或保持 BusLinker 完全断开。此轮不运行 `ping`、`read-position` 或任何写/运动命令。

任一步遇到不能登录、UIO 不匹配、`ERR incompatible_pl_id`、无跳线却 `ENABLED`、有跳线却 `DISABLED`，立即停止并保持 BusLinker 断开。旧 G1 的单舵机只读验收已归档，不在新针位镜像上重复；G2 运动须另行授权并先完成真实标定与急停验收。

