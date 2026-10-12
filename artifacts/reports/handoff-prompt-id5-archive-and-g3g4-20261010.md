# RTCS 交接提示词：归档 ID 5 故障 + 推进 G3/G4

> 用法：把下面分隔线之间的全部内容整段复制到新窗口的第一条消息即可。
> 生成时间：2026-10-10。基线镜像：`artifacts/sd/image.ub` = `cbd286d7…`，
> `artifacts/sd/BOOT.BIN` = `add830ea…`（PL 未重综合）。

---

# 任务：归档 ID 5 错误运动故障，然后推进 G3/G4

仓库根：`D:\3.Electronic_Information\2026.9-ES_Competition-FPGA-AMD\Zynq-6DOF-RTCS`

板端环境：AX7Z020B / 主机名 `petalinux-rtcs`；UIO 设备 `/dev/uio0`。
板子当前 bitstream 为 **ABI 0x5254000D**，仓库源码为 **0x5254000E**（尚未重综合）。
PetaLinux 2023.2 装在 WSL（`~/tools/petalinux/2023.2`），工程 `~/projects/zynq/petalinux-rtcs`。

## 第一步：先只读这四份，不要重新推导（结论已定）

1. `docs/2.G2-six-axis-calibration.md` 的「2026-10-10 ID 5 宽目标被拒的三轴对照与机理收敛」
   「根因定位」「已确认：raw=[86 07 01 08]」「写回通路」「六轴 CLI 变更」各节 —— 这是权威结论。
2. `artifacts/reports/sweep-id5-id1-20261010.txt` —— ID 5 与 ID 1 的全表差异、窗口反解过程、扫描伪影清单。
3. `docs/3.G3-static-closed-loop.md` 与 `docs/4.G4-dynamic-demo.md` —— 阶段目标与验收证据要求。
4. `.workbuddy/memory/2026-10-10.md` —— 全过程的决策与教训。

## 已定因（直接采用，不要再论证）

**ID 5 拒绝一切远离约 2000 的目标，原因在舵机内部的角度限制窗口，不在本仓库任何代码里。**

- 实测 `0x09 = 0x0786 = 1926`（最小角度限制）、`0x0B = 0x0801 = 2049`（最大角度限制）
  → 允许窗口 `[1926, 2049]`。`dump` 的 `gap_09_0c` 一次读 4 字节即可复核。
- 判据：目标 2000 从起点 2322 / 2059 / 1932 全部成功（位移最大 322 步）；
  1900 / 2100 / 2200 / 1500 / 1000 / 2500 / 3000 全部被拒，且被拒时
  `write_sent=1`、`phase=write_ack`、`elapsed_ms=5`、状态包 `ERROR=0x10`（bit4 角度）。
- 已逐项排除：PL 限位（ID 5 表值 0..4000 会放行）、组帧与校验和、原始速度与时间参数、
  行程大小、运动方向、机械干涉（卸力后手推 0..4000 自由通过）。
- **重综合 bitstream 不可能修好它**：`hx30hm_g1_engine.sv` 在 `rx_index==4` 取的就是状态包的
  ERR 字节，`0x10` 是舵机自己回的，PL 只是如实上报。
- 为什么曾"看起来像代码回归"：窗口以**标定当时舵机所在位置**为中心，参考姿态附近的测试全部
  静默通过，直到第一次命令远离参考姿态的目标才暴露。
- 该舵机有多项非出厂 NVS 值（`0x1F=−121`、`0x0E=140`、`0x0F=45`、`0x1C=3000`、`0x15=16`），
  证明有人用外部工具写过它的 EEPROM；本仓库无任何代码写 `0x09/0x0B`（已 grep 确认）。

## 第二步：收尾 ID 5（板端执行，按顺序，务必支撑好机械臂）

`rtcs-buslinker-g1` 有一条白名单写通路 `write-reg`，只允许 `0x09`/`0x0B`/`0x37`，
必须 `--confirm-write`，只单播，写前写后各读回一次。**先做可回退试探：**

    sudo rtcs-buslinker-g1 --device /dev/ttyACM0 --id 5 --addr 0x37 --value 1 --confirm-write write-reg
    sudo rtcs-buslinker-g1 --device /dev/ttyACM0 --id 5 --addr 0x09 --value 1500 --confirm-write write-reg
    sudo rtcs-buslinker-g1 --device /dev/ttyACM0 --id 5 --addr 0x0B --value 2600 --confirm-write write-reg
    sudo rtcs-buslinker-g1 --device /dev/ttyACM0 --id 5 dump
    sudo rtcs-pl-g2 --uio /dev/uio0 move --id 5 --target 2500 --speed-raw 500 --time-raw 10 --execute

`0x37` 写入锁=1 时对 NVS 的写入**掉电不保存**，所以断电即恢复 1926/2049。
若 2500 由拒转变通过 → 因果确认。随后逐步外扩，实测 ID 5 的真实机械行程，
填进 `config/g2_measured_limits.toml` 的 `[[axis]] servo_id = 5`（**现值 0/4000 是无效占位值**）。
满意后把锁写回 0 并重写窗口以持久化。**不要把窗口一次开满**：那会撤掉舵机自身保护。

PL 侧仍有两处未生效的修复（0D 的发前 READ 门禁、`fault 16` 假失败）与新限位表需要重综合：

    cd artifacts/vivado && /d/3.Electronic_Information/vivado/Vivado/2023.2/bin/vivado.bat \
      -mode batch -source ../../src/pl/vivado/create_project.tcl \
      -log ../logs/vivado.log -journal ../logs/vivado.jou -tclargs build ttl

跑完用 `scripts/petalinux/create_project.sh --import-hw` 导入新 XSA，再打镜像。

## 第三步：精简文档 + 归档

- 按仓库惯例新建 `artifacts/archive/<名字>-<日期>/`，含 `README.md` 与 `SHA256SUMS`；
  README 用「证据 / 目前可作的推断 / 尚缺证据」三栏，**禁止把缺失证据补写成成功**。
- 把 ID 5 的重复描述收敛到 `docs/2` 一处，其余位置改为链接；`docs/history/*` 是历史快照，**不要改**。
- 归档内容：本故障的完整证据（`dump`、`sweep`、`move` 日志）、写通路的前后读回输出、镜像哈希。
- 归档前若缺原始板端输出，用上面的命令补齐，不要用转述代替原始输出。

## 第四步：推进 G3 / G4

**G3 前置（当前仍缺，先补齐再动）：**
- 只读四件套连续通过：`probe` / `limits` / `diagnose` / `torque-status --id 5`；
- 工位六段（待机 / 接近 / 夹取 / 抬升 / 放置 / 退出）的**实测**六轴目标，六个原始 count；
- 夹爪实际 ID 与开合行程（**不要假定 ID 6 是夹爪**）、关节方向、负载与障碍边界；
- 软件 stop 延迟与独立断电急停的原始记录（尚未入库）。

**G3 实施顺序：** 离线任务表校验（`python scripts/g3_offline_plan.py config/g3_station_plan.template.json`
对空模板必须返回 `G3_PLAN_REJECTED`）→ 离线工位表填实并逐点检查 → **单循环人工监督**
（每步确认物理结果才进入下一步，不自动重试、不返回限位端点）→ 受控自动状态机
（`src/pl/rtl/trajectory_engine.sv` 目前只是空接口，需实现 FIFO、轨迹、截止时间、IRQ、看门狗）
→ **100 次静态循环**，逐次记录成功率、六轴最大目标误差、抓取结果与人工干预。

**G4：** 在 G3 静态闭环稳定后，加 PS 侧视觉、相机标定、像素→世界坐标、FK/IK、任务状态机与
截止时间生成；再做传送带/动态目标下的故障注入、端到端延迟与 P99 抖动、长期运行与可复现演示。
**视觉不得替代 PL 的急停、看门狗与舵机时序职责。**

## 纪律（必须遵守）

- 每次改动后跑 `wsl.exe -e bash -lc "cd <repo> && bash sim/run_regression_wsl.sh"`，
  必须得到 `RTCS_WSL_REGRESSION_PASS`。
- 改 CLI 后必须重建 `artifacts/sd/`，保持源码与镜像一致；`BOOT.BIN` 未变只说明 PL 未重综合。
- 不谎报结果；失败就写失败；`UNAVAILABLE` 不许回填成数值；不自动重试、不放宽容差、不忽略 ERROR。
- 本环境限制：从 Bash 调用 `powershell`/`cmd` 会被内置安全策略拒绝，**命令文本里出现那些字面词
  也会导致整条命令被拒**（含 `grep` 模式与注释）；Vivado 只能用 `vivado.bat` 直接调。
- 不要删 `.workbuddy/` 目录。

---

## 附：本次交接的基线哈希（新窗口可据此确认起点一致）

| 文件 | SHA256 |
| --- | --- |
| `artifacts/sd/BOOT.BIN` | `add830eafb3797b29dc2a2bb2261b59ca3b8ee080f9e175e1a56090307b0326f` |
| `artifacts/sd/image.ub` | `cbd286d7b44c856e3ec6321bcfc3180177dd327d432f3eda849d612efbaa8300` |
| `artifacts/sd/boot.scr` | `8c429c49293a5827c22a97940be5beab0928e81aaae43ffa0369cdf323cd156a` |
