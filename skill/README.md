# skill/ 技能包索引

赛题 3.3.5.2：技能包置于 `skill/`，每一项须写明**适用场景、使用方法、已验证的效果、失效条件**，
评价标准是"一支陌生队伍拿到该目录，能否直接用在自己的题目上"。本目录两项技能，按此四栏登记。

```
skill/
├── README.md                        ← 本文件（索引与四栏说明）
├── zynq-6dof-rtcs/                  ← 技能 1：AXI 外设 bring-up 与 PS/PL 改动流程
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   └── references/repository-guidance.md
└── rtcs-image-build/                ← 技能 2：Vivado + PetaLinux 可复现构建
    ├── SKILL.md
    └── agents/openai.yaml
```

---

## 技能 1 · `zynq-6dof-rtcs`：AXI4-Lite 外设 bring-up 与硬实时改动流程

| 栏目 | 内容 |
| --- | --- |
| **适用场景** | PS(Linux) + PL(自定义 AXI4-Lite 外设) 共同驱动**物理执行器**的任何工程：舵机、步进、传感器、单线半双工总线。不限于本台的六轴机械臂。 |
| **使用方法** | 触发词 `使用skill修改`（改代码）或 `使用skill解释`（只读讲解）。`SKILL.md` 里是两套 workflow：修改流程 5 步（复述目标→只读相关文件→跨 PS/PL 契约同步→跑最小可验证集→报告改动/证据/风险）；解释流程 5 步（相关文件→总体流程→模块逐一→实现与占位分离）。`references/repository-guidance.md` 是"源真相在哪"的路径表，换题目时替换此表即可复用。 |
| **已验证效果** | 本仓库 2026-09-29 至今的每一次 PS/PL 改动都走这条流程；`sim/run_regression_wsl.sh` 的 9 个 RTL testbench + 6 组 CLI 守卫全绿（`RTCS_WSL_REGRESSION_PASS`），ABI 从 0x02 迭代到 0x0E 未出现"寄存器语义两侧不一致"事故。 |
| **失效条件** | ① IO 电平/方向未核验时不可用（`SKILL.md` 明确禁止）；② 需要 DMA/HLS/中断密集流时，本技能只覆盖 AXI4-Lite 寄存器语义，不覆盖高带宽数据通路；③ 若没有独立于处理器的输出禁用手段（本工程是物理禁发跳线 + 硬件急停），"安全边界"一节不成立。 |
| **来源（从哪些失败总结）** | ① 早期"发运动命令前先预读起点"的门禁，把舵机一个**瞬时** ERROR 位放大成跨命令粘滞的全局锁死，拖了一周——于是定"当次错误当次报，不做持久锁存"；② 把 `ID2 ≤ 2000` 这条几何推测写成硬门禁，直接挡住已实测的 place 位点，当天进度停摆——于是定"会阻止执行的检查默认只告警，位点只认实测"；③ 夹爪夹紧时过载回包把整条 `move-six` 拖死——于是有逐轴忽略掩码。 |

**可迁移的通用部分**（`SKILL.md` 末节 "Reusable AXI peripheral bring-up baseline"，与本题无关）：
先定版本化寄存器映射再写 RTL、物理输出复位默认关断、单设备 + 逻辑分析仪先证协议再上多设备、
描述符原子提交、把时延与抖动的标称值和故障路径一起测、保留纯主机基线以量化"搬进 PL 的收益"。

---

## 技能 2 · `rtcs-image-build`：Vivado + PetaLinux 可复现构建

| 栏目 | 内容 |
| --- | --- |
| **适用场景** | 任何 Zynq-7000 / MPSoC 工程要"从源码到可启动 SD 卡"的构建：Vivado 导出 XSA → PetaLinux 导入现有工程 → 出 `BOOT.BIN` / `image.ub` / `boot.scr` / `SHA256SUMS`。 |
| **使用方法** | 触发词 `镜像构建：`，冒号后写本次约束。5 步：校验仓库与 `git status` → `scripts/build_vivado.ps1 -Build`（必须时序满足且 bit/XSA 非空）→ PetaLinux `create_project.sh --import-hw` 导入**新** XSA → `build_sd_image.sh` 出卡文件并 `sha256sum -c` → 报告 WNS/TNS、路径、哈希与未完成项。 |
| **已验证效果** | 本仓库 `artifacts/hw/rtcs_system.{bit,xsa}`、`artifacts/sd/{BOOT.BIN,image.ub,boot.scr,SHA256SUMS}` 均由该流程产出并上板启动；综合报告 `artifacts/reports/utilization.rpt`（LUT 12.69%）与 `timing_summary.rpt`（100 MHz 全满足）可追溯。 |
| **失效条件** | ① 无 Vivado/PetaLinux 许可与 WSL 环境时不可执行；② 只证明"构建可复现"，**不证明板卡启动、USB 枚举或舵机可用**（`SKILL.md` 已写死不许宣称）；③ 不授权写实体 SD 卡、烧 QSPI 或下发舵机指令——这些必须由操作者在场手动完成。 |
| **来源（从哪些失败总结）** | ① 2026-10-17：示教把 ID2/ID4 实测可达点改宽，只同步了 `config/g2_measured_limits.toml`、没同步综合进 bitstream 的 `g2_board_limits_pkg.sv`，板端 `move-six` 以 fault=12 直接拒发——于是 `check_limit_sync.py` 成为打包的第一道硬检查；② 载荷靠手工拖拽，重打包时 `rm -rf` 把 `static_grasp_server.py` 一起删了，现场变成"PC 发坐标、板端没人收"——于是改成脚本生成 + `cmp` 逐字节对正本；③ 板端 Python ≤3.11 不支持 f-string 嵌套同类引号，本地 3.13 编过、板上 `SyntaxError`，runner 秒退且无一行日志——于是有 `check_py_compat.py`。 |

---

## 与"通用 PYNQ Skill 加分"的关系（如实说明）

赛题对**面向 PYNQ 框架且不绑定本题**的技能单独加分。本队作品**没有使用 PYNQ**：
PL 侧是手写 SystemVerilog + AXI4-Lite 寄存器组，PS 侧是 PetaLinux 上的 C/C++ UIO 程序，
因此不申报 PYNQ Skill，也不把普通构建流程包装成 PYNQ Overlay。
技能 1 的"通用 AXI 外设 bring-up 基线"是可迁移到 PYNQ 工程的方法论（Overlay 加载与寄存器映射
同样适用），但按赛题口径，只有真正跑在 PYNQ 框架上才算加分项，故本目录不作此声明。
