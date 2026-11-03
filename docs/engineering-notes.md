# 工程参考（Engineering Notes）

本文件是仓库唯一的**技术参考**，替代此前 G0–G6 各阶段的独立记录（那些文件记录的是
推进过程，结论已并入本文与 `report/report-1031.tex`，过程记录不再单独维护）。

阅读顺序：先 `report/`（设计与指标），再本文（接口、参数、命令、坑），最后 `evidence/`（原始数据）。

---

## 1. 硬件基线

| 项 | 取值 |
| --- | --- |
| 板卡 | ALINX AX7Z020（XC7Z020CLG400-2），PS 双核 A9 + 1 GiB DDR3，PL 85K LC |
| PS 可见地址 | `0x43C0_0000`，64 KiB 窗口，`generic-uio` |
| 舵机 | 6× HX-30HM 总线舵机，1 Mbps 8N1 半双工单线；ID1–5 关节、ID6 夹爪 |
| 转接 | 幻尔 BusLinker-V3.0，跳帽置 `Servo–TTL`；误置 `USB` 会让 PL 失去总线控制权 |
| 相机 | 中奥维柯 3 mm / 90° 无畸变 UVC + CPL，1280×720 / YUY2 / dshow，设备号 1，无深度 |
| 上位机链路 | USB-UART 115200 8N1，与控制台共用一条链路 |
| 构建 | Vivado / PetaLinux 2023.2（推荐 2026.1/2025.2，脚本可直接重跑） |

**安全边界**：舵机独立 5–14 V 供电、与板卡共地；`g1_inhibit` 跳线接地才允许发帧，拔掉立即禁发；
限位/速度上限/截止时间都是**编译期常量**，改它们必须重综合。

### 1.1 实测限位（`config/g2_measured_limits.toml`，2026-10-12 板端 `limits` 回读）

| ID | min | max | reference | speed_raw_max |
| --- | --- | --- | --- | --- |
| 1 | 1000 | 3000 | 2000 | 1500 |
| 2 | 861 | 1500 | 861 | 1500 |
| 3 | 2000 | 3117 | 3117 | 1500 |
| 4 | 2000 | 2861 | 2861 | 1500 |
| 5 | 0 | 4000 | 2000 | 1500 |
| 6 | 1585 | 2500 | 1585 | 1500 |

`count` 不是角度：`counts_per_90_degrees_approx = 1000` 只是换算近似值，**任何位点只能来自现场
`diagnose` 回读，不得按几何比例推算**（曾按比例推抬升位，撞上底座，fault=9）。

---

## 2. 软硬件接口

### 2.1 AXI 寄存器（ABI `0x5254000E`）

| 用途 | 偏移 |
| --- | --- |
| G1 单轴：ID / OP / CMD / STATUS / RESULT / FAULT | `0x50 / 0x54 / 0x58 / 0x5c / 0x60 / 0x64` |
| G2 六轴：目标、速度、时间、掩码，逐轴 ×6 | 见 `src/pl/rtl/rtcs_pkg.sv` |

G1 故障码：0 正常、1 非法 ID、2 非法操作、3 超时、4 长度、5 停止位、6 应答 ID、7 校验、
8 舵机错误、13 该操作码不允许走 G1 路径。寄存器语义的唯一权威是
`src/pl/rtl/rtcs_pkg.sv` + `src/ps/linux/include/rtcs_registers.hpp`，两处必须同步、改动即升 ABI。

### 2.2 上位机 ↔ 板端串口协议

一行一个 JSON，板端容错地取 `{...}`（终端回显不影响解析）：

```json
{"cmd": "static_capture", "x_mm": 372.2, "y_mm": 36.1, "stable_s": 0.6, "conf": 0.84}
```

`cmd` 取值 `static_capture`（整轮七步）/ `dynamic_stage`（只扑向拦截点）/ `dynamic_close`（只闭爪）。
缺 `x_mm`/`y_mm` 属协议错误，直接拒收；`x` 不在示教区间、`y` 偏离车道超过 8 mm、`conf<0.45`
都只**告警不拦截**（见 `scripts/static_grasp_server.py::validate`）。

板端回一行 `GRASP_RESULT ... grip=contact|empty grip_pos=<count> cycle_ms=<ms> fault=<n>`，
`grip=empty` 表示动作全绿但夹爪合到底——这是判定失败的唯一可靠依据。

### 2.3 视觉坐标约定

原点 = 传送带左下角，`+x` 沿带长、`+y` 沿带宽，单位 mm；标定区域 490×80 mm。示教表必须建在同一
坐标系下。视觉只输出平面 `(x, y)`，**不输出 yaw**，带外不外推。

---

## 3. 板端命令速查

全部形如 `sudo <程序> --uio /dev/uio0 <动词> [参数]`；板端 shell 是 dash，**一次只执行一条**。
只读命令不接受 `--execute`，带运动帧的命令必须显式 `--execute`。

| 命令 | 用途 | 发帧 |
| --- | --- | --- |
| `rtcs-pl-g2 … probe` | 读 ABI + UIO 映射 | 否 |
| `rtcs-pl-g2-six … limits` | 读编译期限位/参考位/速度上限 | 否 |
| `rtcs-pl-g2-six … diagnose` | 逐轴只读位置 + 故障解释 | 否 |
| `rtcs-pl-g2-six … torque-status --id N` | 读扭矩开关（`0x28`） | 否 |
| `rtcs-pl-g2 … move --id N --target T --speed-raw S --execute` | 单轴绝对目标 | 是 |
| `rtcs-pl-g2-six … move-six … --execute` | 六轴同步广播（无 ACK） | 是 |
| `rtcs-pl-g2-six … stop --execute` | 读当前位置后原地保持 | 是 |
| `rtcs-pl-g2 … release --id N --execute` | 卸力 | 是 |

`move-six` 的两个掩码参数：`--ignore-error 6`（夹持期屏蔽 ID6 过载回包）、
`--ignore-arrival 6`（ID6 不参与"连续三轮进带"判定）。

---

## 4. 七步工位状态机

`standby → approach → grasp → lift → place → retreat → exit`，位点与速度在
`config/g3_station_plan.json`（分级速度：standby/approach/grasp 1000、lift/place 1200、
retreat/exit 1400 步/s，夹爪 800 闭 / 900 开）。三条机制缺一不可：

1. **PL 逐轴忽略掩码 `0x11C`**：夹紧时的舵机过载不再拖死整条 `move-six`。
2. **夹持期 `--ignore-arrival 6`**：ID6 在过载保护下位置漂移，不拖满观察期。
3. **`retreat` 步**：张爪后先垂直抬升再横移，避免扫倒已放置的物块。

抬升段必须六轴联动（ID2 单轴走到接近竖直会掉进低速死区停在中途）；离地前不许横移；带件横摆
必须保持高位先单轴摆到位再六轴下放；腕部两轴全程同步跟随，否则工件被拧下。

速度上限 `SPEED_MAX_RAW = 1500` 是编译期常量（`rtcs_pkg.sv` / `rtcs_top.sv` / 控制器三处），
超过直接 `fault=15` 且一帧不发。2026-11-03 试过整机顶到 1500，place 段失速导致抓完不放置就复位，
已退回分级值；要调速用 `scripts/set_plan_speed.py`，只动少数几步。

**夹持判据**：闭爪命令 2200，停在 2364–2409 为夹住（差 170+ count），停在 2214–2216 为夹空，
阈值取 60 count。闭爪耗时同样可判：夹住约 1010 ms（等满观测窗），夹空约 560 ms。

---

## 5. 连续抓取（模式一）

```
x_int   = x_now + v × (advance + move + margin)      夹在窗口 [350, 390] mm
t_block = 物块中心到达 x_int 的时刻
t_close = t_block − advance                          advance ≈ 300 ms（命令→咬合）
t_stage = t_close − move − margin                    move = 1952 ms（exit→370 实测）
```

带速每轮现估：最近 12 帧最小二乘，实测 60.4–66.7 mm/s。**硬约束**：
`检测线 ≤ 窗口下沿 − v×(advance+move+margin)`；v=67.14 时为 162 mm，当前检测线 120 mm，
余量 42 mm。带速更高必须前移检测线，否则 `t_stage < 0`，臂必然晚到。

闭爪不能走 runner（启动 880 ms ≈ 物块走 59 mm），必须走
`static_grasp_server.dynamic_close` 直调 `rtcs-pl-g2` 的单轴快路径，`speed_raw=1500`，
`observe_ms ≥ 600`（否则夹空被误判为 contact）。

**调参口诀**：`grip=empty` 且 `x_trig` 正常 = 太晚（advance −50 ms）；物块被顶回/撞翻 = 太早
（advance +50 ms）；`G5_WARN 来不及 (stage_in<0)` = 检测线前移或降带速。

---

## 6. 视觉侧约束（已知边界，写进任何对外材料时都要带上）

1. 训练 73 张 / 验证 30 张，验证集参与早停选权重，**不是独立测试**；跨机位跨光照未验证。
2. 不做内参标定，镜头畸变被平面映射吸收；**物体高出标定平面时有视差**，是系统性误差。
3. 只输出平面毫米坐标，不含 yaw；`bbox_mm` 可粗算朝向但未验证。
4. 标定区域 490×80 mm 是一条窄带，带外不可信。
5. 背景只对黄色桌面与绿色传送带两种工况负责；不做通用背景鲁棒性。
6. 相机把夹爪误识别为 ID5 舵机时，读出的 `y` 会偏到 50 几——这是误检，不代表夹取位置偏；
   当前靠固定基座位姿规避，未纳入自动闭环。

反光治理（2026-10-15 定案，不要回退）：绿带白方块不可检的根因是光面 PVC 皮带镜面高光 +
自动曝光过曝；治理顺序为压曝光 → 调灯/角度 → 换 90° 无畸变镜头 + CPL。**换相机 = 工况重置**，
旧标定与训练数据全部作废。

---

## 7. 本机与板端环境

- 本机（跑视觉）：`env.cmd` 激活 venv，venv 固定在 `D:\rtcs-venv`。**不要用项目内 `.venv`**——
  仓库路径 260 字符会撞 Windows MAX_PATH。依赖见 `requirements-vision.txt`（CPU 版 torch）。
- 本机无 CUDA，训练只能 CPU 挂机或用免费云。
- 板端：登录后把载荷拷到 `~/rtcs`（该目录在 RAM，断电即丢），5 个 `.py` → `~/rtcs/scripts/`，
  4 个配置 → `~/rtcs/config/`。载荷由 `bash scripts/stage_sd_payload.sh` 从正本生成，
  **不要手工拖拽**；改完必须用 `cmp` 逐字节核对正本。

---

## 8. 高频故障表

| 现象 | 原因与处理 |
| --- | --- |
| `limits` 读出旧范围 | 板端还是旧镜像；先核 ABI 与限位，再发命令 |
| `move-six` 报 `fault=5 write_sent=0` | 描述符守卫拦下：限位/未标定/物理禁发/截止时间/总线占用，逐项查 |
| 某轴不动 | 先查独立供电与接线；上电 `0x28=0` 卸力，**不要靠加大 speed 去顶** |
| 夹爪报 `0x20` | 过载，如实记录；接触位置随工件变化，不是通用闭合 count |
| `calibrated_mask` ≠ `0x3f` | 有轴未标定，`move-six` 直接拒答 |
| 串口"收到回包" | 那是终端回显被当成回复；关闭本地回显或按 `{` `}` 提取 |
| 闭爪一帧不发 | `observe_ms` 低于板端下限被 C 命令判参数错误 |
| 判"未越线"永远成立 | 清标志写在判断之前，改成先判后清 |
