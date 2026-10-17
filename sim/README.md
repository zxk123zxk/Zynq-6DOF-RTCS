# Verification plan（验证计划）

测试平台必须独立于板级引脚约束；**仿真通过不等于实物通过**，只有波形不能宣称已完成真实舵机验证。

## 唯一回归入口

在 WSL 中于仓库根目录运行：

```bash
bash sim/run_regression_wsl.sh
```

通过时输出 `RTCS_WSL_REGRESSION_PASS`（Verilator 5.008，`--binary --timing`）。它串起 AXI 寄存器、HX-30HM 协议、G1 安全/ TTL 顶层、六轴描述符与控制器、单轴连接路径，以及三个 CLI mock 守护。**任何 RTL 或 CLI 改动后必须重跑并 PASS 才能交付。**

单独的守护脚本（调试时用）：

| 脚本 | 作用 |
| --- | --- |
| `sim/run_axi_lite_regs.ps1` | AXI4-Lite 寄存器组（Icarus 备用路径） |
| `sim/run_hx30hm_protocol.ps1` | HX-30HM 报文运算与校验和黄金向量 |
| `sim/run_hx30hm_g1_engine.ps1` | 1 Mbps PING/READ、原子扭矩+位置帧、卸力帧、超时 |
| `sim/run_rtcs_g1_safe_top.ps1` | 无 TTL 顶层必须忽略 G1 命令且保持 `servo_tx_en=0` |
| `sim/run_rtcs_g1_ttl_top.ps1` | 默认禁发、跳线后才允许 TX、拆除立即中止 |
| `sim/run_g2_descriptor_guard.ps1` | 六轴描述符原子捕获与非法/未标定/越限拒绝 |
| `sim/run_rtcs_g2_one_servo.ps1` | 单轴连接路径：禁发、越限、帧字节、±15 反馈边界 |
| `bash sim/run_pl_g1_cli_abi.sh` | CLI 在 ABI 02 上拒绝写寄存器，ABI 08 允许只读 probe |
| `bash sim/run_pl_g2_cli_guard.sh` | 单轴 CLI 的 ABI/字段宽度/禁发检查与打包 |
| `bash sim/run_pl_g2_six_cli_guard.sh` | 六轴 CLI：`move-six`/`stop`/`diagnose` 的 mock 校验 |
| `bash sim/run_g2_one_servo.sh` | 连接态单轴 G2 路径（WSL Verilator） |
| `bash sim/run_buslinker_g1_dump_guard.sh` | BusLinker `dump`/`sweep` 严格只读：逐帧断言只发 READ |
| `bash sim/run_g3_offline_plan_guard.sh` | G3 离线任务表门禁（**归档轨**，见下） |
| `bash sim/run_g3_station_runner_guard.sh` | G3 状态机编排层：六步顺序、故障留痕不锁死、越界拒绝、抓取点覆盖（mock move-six，不碰 UIO） |

## 当前覆盖范围

- **AXI4-Lite**：同步复位、只读寄存器、AW 先到/W 先到/同周期写、保持的 B/R 应答、非连续字节写、六轴目标寄存器独立读回、0x100 以上地址不混叠。
- **HX-30HM 协议**：1 Mbps 8N1 PING/READ、原子 `OP_TORQUE_MOVE`（`0x28=1` + 目标/时间/速度，长度 0x0B）、`OP_TORQUE_OFF`、完整 62 字节六轴广播帧（每轴 `0x28=1`）与校验和；广播完成不等应答。
- **G1 顶层**：默认物理禁发；只有禁发跳线接地才允许 TX；事务中止后不自动恢复；G1 白名单对任何能写位置的操作码报 `fault=13` 且不发字节。
- **G2 六轴**：未标定掩码为零时不发 WRITE、越限拒绝、同步提交、故障后剩余轴有界只读补采、连续三轮全轴到位判定、5 秒观察窗口超时**不重发**、`stop` 先 READ 再广播保持。
- **G2 单轴（ABI 0E 语义）**：先 WRITE 后反馈、正常 ACK、目标已在误差带内、超时不自动重发、故障 ID/阶段/`DIAG[23:16]` 锁存检查。
- **board limits**：用实际六轴综合常量逐轴覆盖最小值/最大值及相邻越界值，并检查速度原始字段 0/500/1500/1501。

## G3 离线任务表门禁（归档轨）

`scripts/g3_offline_plan.py` 只做离线 JSON/TOML 检查并打印一条待人工审阅的命令，**不访问 UIO、不执行运动**。`bash sim/run_g3_offline_plan_guard.sh` 逐条钉住它：空模板必须被拒、缺 `id5_fault_cleared_by_operator` 必须被拒、越界目标必须被拒（同时证明 `safe_min`/`safe_max` 真被读到）、已确认任务表在 `--step standby` 通过且只打印一条 `MANUAL_REVIEW_ONLY`、`motion_executed=0`、`--log` 缺失时拒绝。

> **按双轨制，这套门禁只属于归档轨，不是竞赛轨运动的前置条件。** 该脚本需要 `tomllib`（Python 3.11+），对只带 Python 3.10 的主机有严格 fail-closed 回退解析（只读 `servo_id`/`safe_min`/`safe_max`，解析失败即抛错，绝不返回空限位）。

## 新增测试的写法

每项测试都应由本目录的脚本执行、注明仿真器与版本；新测试加入 `sim/run_regression_wsl.sh`。踩坑记录：`grep -c` 数的是行数，一行六个 `--axis` 只算 1，须用 `grep -o ... | wc -l`。
