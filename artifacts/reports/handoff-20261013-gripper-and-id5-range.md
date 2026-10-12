# 明日推进提示词（2026-10-13 · W1 第 2 天）

> 用法：把下面 `---` 之间的整段复制到新会话作为第一条消息，或直接照着执行。
> 本文件定位：G3 步骤 1 —— **夹爪（ID 6）角色与方向实测**，是当前最关键的一个未知项。

---

你是 `Zynq-6DOF-RTCS` 项目的技术协作者，工作目录 `D:/3.Electronic_Information/2026.9-ES_Competition-FPGA-AMD/Zynq-6DOF-RTCS`。

## 背景（已确认，不要再验证或质疑）

- 板端 ABI `0x5254000E` 已实测，`physical_tx=ENABLED`，`calibrated_mask=0x3f`。
- **ID 1–5 是关节舵机，ID 6 是夹爪舵机**（平行两指夹爪）。这台机械臂是 **5 自由度 + 夹爪**（SO-ARM101 风格）。
- ID 5 的旧窄角度窗口已解除，远端目标可正常到达（10-12 实测 `--target 1500` 由 1907 → 1510，`fault=0`）。
- 上电后 `0x28` 扭矩开关为 **0（卸力）**；运动命令会在同一条原子帧里写 `0x28=1`，所以直接下 `move` 即可。
- **只有装上 J20-36/W15 → J20-38/GND 的允许跳线才能发帧**；舵机独立供电；断电急停是独立硬件路径。

## 今天的唯一硬目标

**测出 ID 6 夹爪的"开"与"合"方向，以及两者的原始 count，并写入配置。**

这是 11.04 交付前最关键的一个未知项——不知道夹爪方向，G3 的抓取步就写不出来。

### 执行步骤

**第 0 步（每次上板必做，30 秒）**

    sudo rtcs-pl-g2-six --uio /dev/uio0 limits
    sudo rtcs-pl-g2-six --uio /dev/uio0 diagnose

期望 `calibrated_mask=0x3f`、六轴 `servo_error=0x00`、末行 `RTCS_PL_G2_SIX_DIAG OK issues=0 read_only=1 write_sent=0`。

**第 1 步：夹爪单轴小步试探（目视观察）**

ID 6 的命令闭区间是 **1585–2500**。当前位置约 2052。**从当前值出发小步走，不要直接冲到两端**，避免撞硬限位。以下命令**逐条单独执行**（板端 shell 是 dash，不要粘贴多行循环）：

    sudo rtcs-pl-g2 --uio /dev/uio0 move --id 6 --target 1900 --speed-raw 500 --time-raw 100 --execute

观察两指是**张开还是闭合**，记录方向。然后：

    sudo rtcs-pl-g2 --uio /dev/uio0 move --id 6 --target 1750 --speed-raw 500 --time-raw 100 --execute

再往另一侧：

    sudo rtcs-pl-g2 --uio /dev/uio0 move --id 6 --target 2200 --speed-raw 500 --time-raw 100 --execute

    sudo rtcs-pl-g2 --uio /dev/uio0 move --id 6 --target 2350 --speed-raw 500 --time-raw 100 --execute

**判断规则**：哪一侧两指张开、哪一侧两指并拢（或夹紧），就是对方的方向。若某条命令报 `fault=8` 且带 `servo_error_raw`，立刻停止该方向、回退到上一个成功值，把原始输出存下来。

**第 2 步：确定两个工作点**

- **"开"目标**：两指张开到能容下 3D 打印小方块并有明显余量的 count。
- **"合"目标**：两指能夹紧方块（空载时两指接近并拢）的 count。**注意不要让它夹到硬限位而堵转**——如果听到持续异响或看到 `0x45` 电流升高，回退 30~50 count。

**第 3 步：写入配置**

在 `config/g2_measured_limits.toml` 的 ID 6 注释块中补记实测结果（方向、开/合 count、是否有硬限位），并说明证据来源。**只写实测值，不猜。**

**第 4 步（可选，若时间充裕）：ID 5 真实可用区间**

`config` 里 ID 5 的 0–4000 只是命令范围标注，不是实测。可从小步探边界（每条单独执行，遇到拒绝就停并回退）：

    sudo rtcs-pl-g2 --uio /dev/uio0 move --id 5 --target 1200 --speed-raw 500 --time-raw 100 --execute

依次 1200 → 900 → 600，以及 2400 → 2800 → 3200，记录第一个被拒绝的值。**不需要走到极限**，能给出"可用区间至少 [A, B]"即可。

## 记录与验收

- 夹爪方向结论：`越小 = 开/合`，`越大 = 开/合`
- 开 count = ？ 合 count = ？ 证据 = 哪几条命令的输出
- 把完整原始输出存到一处（例如 `artifacts/reports/`），**失败命令的原始输出必须保留，不要只留成功的**

## 另外两位队友今天的任务

- **视觉手**：打印 9×6 / 20 mm 棋盘格；在 PC 上用 OpenCV 跑通 `findChessboardCorners`，先对相机拍一张图确认能稳定检出角点。同时用 `v4l2-ctl --list-formats-ext` 记录该相机实际支持的分辨率与帧率（它是 120° 广角，畸变较强，后面标定必须带畸变系数）。
- **结构/交付手**：确认 3D 打印小方块的尺寸与数量（先做 3 个同规格）；准备一个能固定在工作台上的平面工装，让方块每次摆放位置可复现；顺便拍好机械臂与工位的照片存档。

## 明确不要做

- ❌ 不要动 RTL / bitstream / SD 镜像（板端与仓库已一致，重综合只会浪费一天）
- ❌ 不要在夹爪上直接给 1585 或 2500 这种端点值（会撞硬限位）
- ❌ 不要粘贴多行 shell 循环到板端（dash 会 `syntax error`）
- ❌ 不要去填 `config/g3_station_plan.json` / `g3_observation_log.json` 那套离线归档门禁——按双轨制它不是运动前置条件
- ❌ 不要重跑 ID 5 的窄窗口排查（已定因已解决）

## 纪律

- 板端运动只由人执行、人在场、能随时物理断电。
- 任何 `fault` / 异常动作 / 异响，**停止当次操作并保留原始输出**，不自动重试、不放宽容差。
- 没测到的数据不得写成实测。跑不了的验证要如实说明。

---

## 附：本提示词的依据（无需复制）

- 阶段与门禁：`docs/0.1hardware_bringup.md`（双轨制）、`docs/3.G3-static-closed-loop.md`（G3 步骤 1）
- 六轴基线与夹爪映射：`docs/2.G2-six-axis-calibration.md`
- 日程定位：`docs/7.sprint-plan-daily-tasks.md` 的 W1 表格（10.13 行）
- 扭矩开关前提：`docs/1.G1-single-servo-protocol.md`
