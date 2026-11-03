#!/usr/bin/env python3
"""G3 状态机编排层：读已确认的工位计划，顺序执行六步，故障留痕不锁死。

软状态机（PS 侧任务编排）。每步 = 一次 ``move-six``（subprocess 调用 rtcs-pl-g2-six）。
真正的组帧、总线时序、限位门禁全在 PL；本程序只负责"顺序 + 每步成败判定 + 故障留痕"。

夹爪（ID 6）单独走单轴命令 ``rtcs-pl-g2 move``，不并进六轴到位判定：
夹住物块时舵机必然过载（servo_error 0x20、停在接触位置而不是命令目标），
六轴命令要求六轴全部进容差带，把夹爪并进去只会让每次抓取都判失败。
所以一个抓取动作拆成"六轴到位（夹爪保持张开）→ 单轴闭合（允许过载=夹住了）"。
闭合后读到的接触位置会接管后续各步的 ID6 目标（Hold），避免继续压紧或张开掉件。

抓取点参数化：approach/grasp/lift 三步随 (x, y) 变化的是 ID 1-3；给定 ``--grasp-xy``
时用 :mod:`grasp_point_map` 把平面坐标映射成这三步的目标，盲抓（不给坐标）则用计划里
的固定示教点。同一份程序两种喂点方式。

用法：
  # 盲抓：跑一遍六步
  python3 scripts/g3_station_runner.py config/g3_station_plan.json --uio /dev/uio0 --once
  # 盲抓：连续 10 轮（11.04 兜底视频）
  python3 scripts/g3_station_runner.py config/g3_station_plan.json --uio /dev/uio0 --loop 10
  # 只打印命令不执行（人工审阅；占位步也允许打印）
  python3 scripts/g3_station_runner.py config/g3_station_plan.json --once --dry-run
  # 视觉抓：用映射坐标覆盖抓取点
  python3 scripts/g3_station_runner.py config/g3_station_plan.json --uio /dev/uio0 \
      --grasp-xy 120.5,-30.0 --teaching-table config/grasp_teaching_table.json --once
  # 视觉抓默认跳过 standby（--standby auto）：复位位直接去标定位，省一趟 985 ms 往返。
  # 想恢复旧行为（先到静态待抓位）加 --standby keep。

故障留痕不锁死语义：某步失败 -> 记录该步故障 -> 尝试执行 exit 步安全回位 -> 本轮计失败；
若还有剩余轮次则继续下一轮。exit 步本身失败则立即终止（安全无法保证时不继续）。
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import g3_offline_plan  # noqa: E402  复用其门禁校验
import grasp_point_map  # noqa: E402  抓取点参数化的几何层

STEPS = ("standby", "approach", "grasp", "lift", "place", "retreat", "exit")
# 可以被运行时跳过的步：只允许 standby。
# 视觉抓取时 approach 的 ID1-3 已被标定位覆盖，先到静态 standby 等于白跑一趟
# （10-21 实测每轮 985 ms），而且从静态位横切到标定位会扫过传送带上游。
# 只跳过 standby 是刻意的：其余步负责持件搬移与撤离，跳过任何一步都可能导致碰撞。
SKIPPABLE_STEPS = ("standby",)
# 随平面坐标 (x,y) 变化的三步；ID 1-3 由映射覆盖，ID 4-6 保留该步固定姿态。
# 随平面坐标 (x,y) 变化的两步；ID 1-3 由映射覆盖，ID 4-6 保留该步固定姿态。
# **lift 不在此列**：它是"抓取位 + 竖直抬升"，由 apply_grasp_point 按实测增量推导。
GRASP_STEPS = ("approach", "grasp")
GRIPPER_AXIS = 6
# 逐轴移动顺序：**先动 ID 3（肘），再动 ID 2（肩）**。
# 10-20 实测：夹着物块时 ID3 在大幅移动里可能锁死，如果先动 ID2，ID2 会被 ID3 的
# 连杆挡住，报错却指向 ID2（假象）。先动 ID3，卡了就直接报 ID3，归因才不会错。
PER_AXIS_ORDER = (3, 2, 1, 4, 5)

# 逐轴到达容差（count）。ID 3 在大幅移动时实测会差 60 左右（扭矩不足、非故障），
# 默认 30 会把它判成 fault=9；放宽到 PL 允许的上限 100，让它不阻塞后续动作。
# 只放宽 ID 3；其余轴保持 PL 默认 30，避免掩盖真实碰撞。
AXIS_TOLERANCE = {3: 100}
# 搬运段的通用容差：**只要求大致到位**。
# 2026-11-03 踩到：place 的第一步（ID1 单轴横摆、带着方块转 830 步）没传 --tolerance，
# 落到 C 的默认 30；带载 + 回差让它进不了 30 的带，命令一直等到 PL 的 2 s 截止
# → fault → place 判失败 → 直接走 exit 复位（现场看着就是"跳过放置"）。
# 六轴命令早就给 ID3 放行到 100 了，单轴横摆用的是同一类判断，口径必须一致。
TRANSIT_TOLERANCE = 100
# 夹爪保持时给足容差：物块顶着夹爪，实测位置与命令目标天然有几百 count 的差。
GRIPPER_HOLD_TOLERANCE = 100
# 夹爪开合的观察期（ms）。夹住物块时接触位永远进不了容差带，只能等满窗口才返回；
# 实测夹爪走完全行程 758 ms，1200 足够，空抓/实抓耗时因此一致。
GRIPPER_OBSERVE_MS = 1200
# 放置后的撤离抬升轴：实测 ID 3（肘）与 ID 4 联动决定末端高度，ID 1/2/5 管水平位置。
RETREAT_AXES = (3, 4)
DEFAULT_OBSERVE_MS = 8000
# 舵机 ERROR 的 bit5 是过载电压/电流保护，夹住物块时出现属正常工况，不是故障。
SERVO_OVERLOAD_BIT = 0x20
# 闭合后"观测位置 - 命令目标"小于这个量 = 没有东西挡着，合到底了（空夹）。
# 10-25 实测：夹住 40 mm 方块停在 2370~2401（差 170~201），空夹停在 2214（差 14）。
GRIP_CONTACT_GAP = 60


def step_targets(item: dict, hold: int | None) -> list[int]:
    """该步真正下发的六轴目标；夹爪处于保持态时用接触位置覆盖计划值。"""
    targets = list(item["target_count"])
    if hold is not None:
        targets[GRIPPER_AXIS - 1] = hold
    return targets


def build_move_six_args(uio: str, item: dict, six_cli: str, targets: list[int],
                        observe_ms: int, hold: int | None,
                        loose_id3: bool = False) -> list[str]:
    """把一步工位计划翻译成 move-six 命令参数。six_cli 可带参数（如
    ``python3 mock.py``），用 shlex 拆分。"""
    parts = shlex.split(six_cli) + ["--uio", uio, "move-six"]
    for i in range(6):
        parts += ["--axis",
                  f"{i + 1}:{targets[i]}:{item['speed_raw'][i]}:{item['time_raw'][i]}"]
    tolerances = dict(AXIS_TOLERANCE)
    if hold is not None:
        tolerances[GRIPPER_AXIS] = GRIPPER_HOLD_TOLERANCE
    for axis in sorted(tolerances):
        parts += ["--tolerance", f"{axis}:{tolerances[axis]}"]
    # 夹爪夹紧必然报过载；屏蔽它的 ERROR，避免整条六轴命令被判失败。
    parts += ["--ignore-error", str(GRIPPER_AXIS)]
    # ID3 只在抓取那一步要求精确；其余搬运步骤只要求大致到位。
    # ``loose_id3`` 给**动态拦截的 stage** 用：那一趟的终点是"停在拦截位等着闭爪"，
    # ID3 带载漂几十步不影响抓取，但如果这里要求严格，grasp 就会偶发判失败 →
    # runner 直接走 exit 回位 → 现场看到的"刚要抓取就突然复位"。
    if item["name"] != "grasp" or loose_id3:
        parts += ["--ignore-arrival", "3"]
    # 夹持期间 ID6 顶着物块，位置会在过载保护的一收一顶之间来回漂（实测漂移
    # 常超 100 count）。它的目标已被接触位置钉住，不需要参与"连续三轮进带"判定；
    # 否则整条命令要空等满观察期——这正是实抓时"愣半天才上抬"的直接原因。
    if hold is not None:
        parts += ["--ignore-arrival", str(GRIPPER_AXIS)]
    parts += ["--observe-ms", str(observe_ms), "--execute"]
    return parts


def build_single_axis_args(uio: str, action: dict, single_cli: str) -> list[str]:
    """夹爪开合翻译成单轴 move 命令（rtcs-pl-g2）。

    ``observe_ms`` 默认压到 1200：夹住物块时接触位与命令目标必然差几十~几百 count，
    永远进不了容差带，只能等满观察期才返回——这就是空抓结束时"迅速上抬"、
    实抓时"愣半天"的来源。把窗口压到刚够夹爪走完全行程（实测 758 ms）即可。
    """
    axis = action.get("actuator_id", GRIPPER_AXIS)
    observe_ms = int(action.get("observe_ms", GRIPPER_OBSERVE_MS))
    parts = shlex.split(single_cli) + ["--uio", uio, "move",
                                       "--id", str(axis),
                                       "--target", str(action["target_count"]),
                                       "--speed-raw", str(action.get("speed_raw", 500)),
                                       "--time-raw", str(action.get("time_raw", 10)),
                                       "--observe-ms", str(observe_ms),
                                       "--execute"]
    return parts


def build_retreat_args(uio: str, place_item: dict, exit_item: dict,
                       single_cli: str) -> list[list[str]]:
    """放置后撤离：只抬抬升轴，ID 1/2/5 保持 place 值，避免扫到刚放下的物块。

    从 place 直接走 move-six 到 exit 是**斜着穿过物块顶部**的，实测会碰到已放下的方块。
    这里先把 ID 3 / ID 4（抬升联动轴）单轴抬到 exit 的高度，再让 exit 去走平移。
    """
    cmds: list[list[str]] = []
    for axis in RETREAT_AXES:
        i = axis - 1
        parts = shlex.split(single_cli) + ["--uio", uio, "move",
                                           "--id", str(axis),
                                           "--target", str(exit_item["target_count"][i]),
                                           "--speed-raw", str(place_item["speed_raw"][i]),
                                           "--time-raw", str(place_item["time_raw"][i]),
                                           "--tolerance", str(AXIS_TOLERANCE.get(axis, 30)),
                                           "--execute"]
        cmds.append(parts)
    return cmds


def run_retreat(uio: str, place_item: dict, exit_item: dict,
                single_cli: str, dry_run: bool) -> tuple[bool, str]:
    """执行放置后的撤离抬升；返回 (是否成功, 输出/故障)。"""
    lines: list[str] = []
    for parts in build_retreat_args(uio, place_item, exit_item, single_cli):
        if dry_run:
            lines.append("DRY_RUN " + shlex.join(parts))
            continue
        proc = subprocess.run(parts, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        lines.append(out.strip().splitlines()[-1] if out.strip() else "")
        if "RTCS_PL_G2_OK" not in out:
            fault = next((line for line in out.splitlines() if line.startswith("ERR ")),
                         "no_motion_ack")
            return False, fault
    return True, "\n".join(lines)


def apply_grasp_point(plan: dict, x_mm: float, y_mm: float, table_path: Path) -> None:
    """用映射坐标覆盖 approach/grasp 的关节目标；ID6（夹爪开度）始终取计划值。

    覆盖范围由示教表的轴数决定（见 :func:`grasp_point_map.map_grasp`）：
      * **五轴表**（推荐）→ ID1-5 全部按表插值。教点时臂停在什么腕部姿态，
        运行时就是什么姿态，不存在"教的姿态和跑的姿态不一致"。
      * **三轴表**（旧格式）→ 只覆盖 ID1-3，ID4/ID5 取计划固定姿态。仅当所有
        示教点确实共用同一腕姿时才成立。
      * ID6 在任何情况下都取计划值：它是执行器开度指令，闭合后由接触位置 ``hold``
        接管，不参与姿态插值。

    **lift 不能跟着插值走**（10-21 实际踩过）：它是"抓取位 + 竖直抬升"，不是另一个
    平面位置。早先把 lift 也算进 GRASP_STEPS，结果 lift 的 ID1-3 被写成和 grasp 一样，
    抬升动作消失 → 带着物块在低处横移，直接扫到传送带。

    因此 lift 默认**保持计划里固定的标准抬升位**（唯一被 `--loop 3` 验证过、不撞底座/
    传送带的姿态）。只有在示教表里逐点录了 ``lift_targets`` 时才用实测值覆盖 ID1-3，
    且**绝不按固定增量推导**——10-21 试过，基座偏移 337 count 时撞到底座
    （fault=9 fault_id=4）。

    **但 lift/place 的 ID4/ID5（腕部）必须跟着抓取点走**：五轴表把腕姿改成逐点实测后，
    若搬运段仍用计划固定腕姿，夹爪会带着工件自转（10-23 实测 22° → 方块被拧出来）。
    腕部从夹住到张爪之间一刻都不许动。ID1-3 仍取已验证的固定位，不受影响。

    求值用 ``linear``（同车道）/ ``bilinear``（不同车道）。越出示教区间**只告警不阻断**，
    插值本身两端夹住、不外推。
    """
    table = grasp_point_map.load_table(table_path)
    lo = min(p["x_mm"] for p in table)
    hi = max(p["x_mm"] for p in table)
    if len(table) == 1:
        print("G3_WARN teaching table has only 1 point: --grasp-xy is effectively IGNORED "
              f"(always -> x={table[0]['x_mm']}, y={table[0]['y_mm']}). "
              "Fine for a first end-to-end check; add more points before judging accuracy.",
              file=sys.stderr)
    if not lo <= x_mm <= hi:
        print(f"G3_WARN grasp-xy x={x_mm:.1f} outside taught range {lo:.1f}..{hi:.1f} "
              f"(clamped to the nearest taught pose, not extrapolated)", file=sys.stderr)

    by_name = {item["name"]: item for item in plan["steps"]}

    # 插值方式取 auto：示教点同车道时走"沿 x 分段线性"（≥2 点就能真插值），
    # 否则退回 bilinear（<4 点退化为最近邻）。**3 点在旧逻辑下是纯最近邻**，
    # 误差可达间距一半（10-22 实测三点间距 25 mm → 最坏 ±13 mm，方块夹不住）。
    lane = grasp_point_map.same_lane(table)
    method = "linear" if lane else "bilinear"
    n_axes = len(table[0]["targets"])
    for name in ("approach", "grasp"):
        item = by_name[name]
        # fixed_pose 的用处由表的轴数决定：五轴表只取它的 ID6（夹爪开度），
        # 三轴表整组沿用（ID4/ID5/ID6 = 计划固定姿态）。见 grasp_point_map.map_grasp。
        six = grasp_point_map.map_grasp(x_mm, y_mm, table, item["target_count"][3:6],
                                        method=method)
        item["target_count"][0:6] = six

    grasp_after = list(by_name["grasp"]["target_count"][0:5])
    # lift 的 ID1-3：默认**保持计划里的固定抬升位**（那是唯一验证过不撞底座/传送带的姿态）。
    # 只有当示教表里逐点录了 lift_targets 时才用实测值覆盖。ID4/ID5 见下方"腕部不转"。
    lift_points = [{"x_mm": p["x_mm"], "y_mm": p["y_mm"], "targets": p["lift_targets"][:3]}
                   for p in table if p.get("lift_targets") is not None]
    if lift_points:
        lift_after = grasp_point_map.bilinear(x_mm, y_mm, lift_points)
        by_name["lift"]["target_count"][0:3] = lift_after
        src = f"{len(lift_points)}/{len(table)} points measured"
    else:
        lift_after = list(by_name["lift"]["target_count"][0:3])
        src = "plan default verified pose (not derived)"

    # **搬运期腕部不转**：五轴表下，lift 与 place 的 ID4/ID5 都直接继承抓取点。
    #
    # 10-23 实测踩到的故障：x=345 那一行教出来的腕姿是 ID5=1756，而 lift 用的是固定
    # 抬升位的 ID5=2005 —— 抬升过程中 ID5 要转 +249 count（约 22°），夹爪带着方块自转，
    # 方块被拧出来（夹的时候接触位 2401 正常，抬起来就掉）。同一批的 x=395 只有 +55，
    # 转 5°，就没事。10-22 那 5/5 之所以正常，是因为当时 ID4/ID5 固定成 2789/2009，
    # 与 2005 几乎无差——**逐点插值 ID4/ID5 引入的新故障**。
    #
    # place 也必须跟：它的腕姿是 2709/2005，从 lift 过去还要再转一次 ID5 +249，
    # 只修 lift 的话方块会在放置途中掉。**腕部从夹住到张爪之间一刻都不许动**；
    # place.gripper 张开之后（retreat/exit）已经是空爪，转腕无所谓。
    #
    # 边界：ID1-3 仍是计划里已验证的固定位（决定臂的高度与路径，不许动，撞过底座）；
    # 只有 ID4/ID5 这两个腕部关节跟手，它们不影响臂的可达性，只决定工件朝哪。
    # 三轴表不适用：那时 grasp 的 ID4/ID5 就是计划的 2789/2009，继承过来反而会改掉
    # 已验证的抬升/放置腕姿。
    if n_axes == 5:
        wrist = by_name["grasp"]["target_count"][3:5]
        for name in ("lift", "place"):
            by_name[name]["target_count"][3:5] = wrist
        src += " + wrist follow grasp"

    # **lift 只许垂直抬**：基座 ID1 保持抓取值，水平位移整体交给 place（那时已离地）。
    #
    # 10-23 实测：x=345 那一点 grasp ID1=1854 → lift ID1=2045，抬升中基座要转 +191 count
    # （≈17°，夹爪半径约 300 mm 时弧长近 90 mm），而 ID2 要扛着整条臂升 843 count。
    # 六轴同步插值按同一百分比推进，**轻载的 ID1 先到位、重载的 ID2 起步慢**，
    # 于是基座先转、夹爪带着方块沿带面横扫，靠带子摩擦把方块蹭出来
    # （现场看到的就是"先小幅拖动再抬升"）。10-22 那个点 ID1 只差 +61，所以没暴露。
    #
    # 同一条物理原则在 place→exit 已经用过一次（retreat 步先垂直抬再横移，见
    # build_retreat_args）；pick 侧一直存在，只是没触发。**离地之前不许横向移动。**
    by_name["lift"]["target_count"][0] = by_name["grasp"]["target_count"][0]
    lift_after = list(by_name["lift"]["target_count"][0:3])

    # **lift 的 ID2 分两步**：先单轴走完 1/3，再五轴联动走完余下 2/3。
    # 一次把 ID2 走到底，ID3 就只能在联动里独自走完全程，观感上"别的轴都到位了、
    # 就 ID3 猛然下降"（10-24 反馈）。给 ID2 留 1/3 头、余下与 ID3 一起走，过渡才顺。
    # 存到 lift 步的 _id2_mid 上，run_lift 读它；盲抓（无 --grasp-xy）不设此键，
    # run_lift 回退到一步到底的旧行为。
    _g2 = by_name["grasp"]["target_count"][1]
    _l2 = by_name["lift"]["target_count"][1]
    by_name["lift"]["_id2_mid"] = _g2 - (_g2 - _l2) // 3

    y_spread = max(p["y_mm"] for p in table) - min(p["y_mm"] for p in table)
    # **插值出来的 ID2 也必须过一遍竖直点提示**（10-25 补）：`g3_offline_plan.validate`
    # 是在本函数之前跑的，看的是计划里的静态值，所以 `--grasp-xy` 覆盖出来的姿态
    # 从来没有被这条提示检查过。295 mm 处插值 ID2=2109，已经越过竖直点(~1990)/
    # 提示线 2020，却一声不响——而"展开态带负载"正是 10-19 记下的风险。
    # 只告警不拦截（不做硬门禁）。数值与 config/g2_measured_limits.toml [task] 同步。
    id2_hint = 2020
    for name in ("approach", "grasp"):
        if by_name[name]["target_count"][1] > id2_hint:
            print(f"G3_WARN {name}: ID 2 target {by_name[name]['target_count'][1]} "
                  f"from teaching-table interpolation is above operating hint {id2_hint} "
                  f"(past the vertical point; watch the first lift)", file=sys.stderr)
    print(f"G3_INFO grasp_xyz={grasp_after} lift_xyz={lift_after} "
          f"carry_wrist={by_name['lift']['target_count'][3:5]} | "
          f"lift source: {src} | interp: {method} ({len(table)} points, "
          f"lane={'yes' if lane else 'no'} y_spread={y_spread:.1f}mm, axes={n_axes})")


def run_move_six(uio: str, item: dict, six_cli: str, targets: list[int],
                 observe_ms: int, hold: int | None, dry_run: bool,
                 loose_id3: bool = False) -> tuple[bool, str]:
    """执行一步六轴运动，返回 (是否成功, 输出文本)。"""
    parts = build_move_six_args(uio, item, six_cli, targets, observe_ms, hold,
                                loose_id3=loose_id3)
    cmdline = shlex.join(parts)
    if dry_run:
        return True, "DRY_RUN " + cmdline
    proc = subprocess.run(parts, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 and "RTCS_PL_G2_SIX_OK" in (proc.stdout or "")
    return ok, output


def fault_line(output: str) -> str:
    """抽出故障摘要用于留痕；move-six 与单轴命令的 ERR 行都认。"""
    for line in output.splitlines():
        if line.startswith("ERR "):
            return line.strip()
    return "no_motion_ack"


def run_step(uio: str, item: dict, six_cli: str, single_cli: str,
             targets: list[int], observe_ms: int, hold: int | None,
             transit: str, dry_run: bool,
             loose_id3: bool = False) -> tuple[bool, str]:
    """一步的搬运方式：默认六轴同步；``--transit per-axis`` 仅供排障。

    夹爪的过载已由 PL 的逐轴错误掩码（``--ignore-error 6``）屏蔽，六轴命令不会
    再因为夹紧而整条失败，所以正常运行不需要逐轴。
    """
    if transit == "per-axis":
        return run_per_axis(uio, item, single_cli, targets, dry_run)
    return run_move_six(uio, item, six_cli, targets, observe_ms, hold, dry_run,
                        loose_id3=loose_id3)


def _first_int(pattern: str, output: str, base: int = 10) -> int | None:
    match = re.search(pattern, output)
    return int(match.group(1), base) if match else None


def observed_gripper_position(output: str) -> int | None:
    """从单轴命令输出里取本次到达的真实位置；取不到返回 None（不猜）。"""
    for pattern in (r"incident_position=(\d+)", r"\blast=(\d+)", r"position_raw=(\d+)"):
        value = _first_int(pattern, output)
        if value is not None:
            return value
    return None


def judge_gripper(output: str, action: dict) -> tuple[bool, str, int | None]:
    """判定一次夹爪开合：返回 (是否达成, 语义, 观测位置)。

    闭合夹住物块时必然堵转：舵机停在接触位置并报过载，G2 因此给 fault=5。
    这是夹住的正常工况，不是故障。判定**不依赖计划里的 expect_overload 开关**——
    开关与现场不一致时不该误判成失败：
      RTCS_PL_G2_OK                          -> OK（空合到底或轻夹到位）
      闭合且帧已发出、拿到位置或过载位         -> CONTACT（夹住了）
      张开失败 / 帧没发出                     -> FAULT

    **空夹单独标 EMPTY（10-25 加）**：夹住东西时舵机停在接触位，离命令目标差
    170~200 count；夹空时直接合到目标附近（实测 2214 vs 目标 2200，差 14）。
    10-25 那批 21 次里，10 次"忘放件"全部以 `result=OK position=2214` 记成了成功，
    肉眼看日志分不出来——**这是唯一能自动区分"夹住了"与"夹空了"的信号**，
    所以给它一个自己的名字。只改名、不改成败：不阻断、不中止循环（用户要求
    不做硬门禁），只是让 G3_CYCLE 与证据里能一眼分开。
    """
    position = observed_gripper_position(output)
    if "RTCS_PL_G2_OK" in output:
        if action.get("command") == "close" and position is not None:
            target = action.get("target_count")
            if isinstance(target, int):
                # 停得比目标远一截 → 有东西挡在虎口里；几乎停到目标 → 空合。
                # 两者都可能以 RTCS_PL_G2_OK 返回（接触但没过载时也是 OK），
                # 所以按"观测位置离目标多远"判，而不是只看回包类型。
                if position - target < GRIP_CONTACT_GAP:
                    return True, "EMPTY", position
                return True, "CONTACT", position
        return True, "OK", position
    if action.get("command") == "close" and "write_sent=1" in output:
        raw = _first_int(r"servo_error_raw=0x([0-9a-fA-F]{2})", output, base=16)
        if (raw is not None and raw & SERVO_OVERLOAD_BIT) or position is not None:
            return True, "CONTACT", position
    return False, "FAULT", position


def run_gripper(uio: str, action: dict, single_cli: str,
                dry_run: bool) -> tuple[bool, str, int | None]:
    """执行一步夹爪开合，返回 (是否达成, 语义, 观测位置)。"""
    parts = build_single_axis_args(uio, action, single_cli)
    if dry_run:
        return True, "DRY_RUN", None
    proc = subprocess.run(parts, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    ok, detail, position = judge_gripper(output, action)
    if ok:
        return True, detail, position
    for line in output.splitlines():
        if line.startswith("ERR "):
            return False, line.strip(), position
    return False, "no_motion_ack", position


def run_per_axis(uio: str, item: dict, single_cli: str, targets: list[int],
                 dry_run: bool) -> tuple[bool, str]:
    """逐轴移动 ID 1..5，**完全不碰 ID 6**。

    夹住物块时 ID6 会持续报过载；move-six 的判定是"任一轴回包 ERROR 非零就整条失败"，
    会把这条命令判死。逐轴命令只读被移动的那一轴，夹爪的过载进不来——
    这样夹多紧都不影响机械臂搬运，不需要靠"轻夹"绕。
    """
    lines: list[str] = []
    for axis in PER_AXIS_ORDER:
        i = axis - 1
        parts = shlex.split(single_cli) + ["--uio", uio, "move",
                                           "--id", str(axis),
                                           "--target", str(targets[i]),
                                           "--speed-raw", str(item["speed_raw"][i]),
                                           "--time-raw", str(item["time_raw"][i])]
        tolerance = AXIS_TOLERANCE.get(axis)
        if tolerance is not None:
            parts += ["--tolerance", str(tolerance)]
        parts.append("--execute")
        if dry_run:
            lines.append("DRY_RUN " + shlex.join(parts))
            continue
        proc = subprocess.run(parts, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        lines.append(out.strip().splitlines()[-1] if out.strip() else "")
        if proc.returncode != 0 or "RTCS_PL_G2_OK" not in (proc.stdout or ""):
            fault = next((line for line in out.splitlines() if line.startswith("ERR ")),
                         "no_motion_ack")
            return False, fault
    return True, "\n".join(lines)


def run_lift(uio: str, item: dict, six_cli: str, single_cli: str, targets: list[int],
             observe_ms: int, hold: int | None, dry_run: bool) -> tuple[bool, str]:
    """**已弃用（2026-10-24），不要重新接回 run_plan。** 保留仅为历史对照。

    抓取后的抬升：先单独把 ID2 抬到目标（优先离带），其余四轴再六轴联动。

    10-23 定案：抬升阶段若让 ID1/ID3 与 ID2 一起走六轴同步插值，轻载轴先到位、
    重载的 ID2/ID3 拖后腿，夹爪还没离带就被横带/低头栽到带面拖行。拆成两段——
    先 ID2 拉高，夹爪一旦离带，ID1/ID3/ID4/ID5 再联动就不蹭带。ID6 由 ``hold`` 钉住，
    完全不碰（夹持期已 --ignore-arrival 6）。
    """
    parts = shlex.split(single_cli) + ["--uio", uio, "move",
                                       "--id", "2",
                                       "--target", str(item.get("_id2_mid", targets[1])),
                                       "--speed-raw", str(item["speed_raw"][1]),
                                       "--time-raw", str(item["time_raw"][1]),
                                       "--execute"]
    if dry_run:
        first = "DRY_RUN " + shlex.join(parts)
        ok_first = True
    else:
        proc = subprocess.run(parts, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        first = out.strip().splitlines()[-1] if out.strip() else ""
        ok_first = proc.returncode == 0 and "RTCS_PL_G2_OK" in (proc.stdout or "")
    if not ok_first:
        return False, first
    ok, rest = run_step(uio, item, six_cli, single_cli, targets,
                        observe_ms, hold, "six", dry_run)
    return ok, first + "\n" + rest


def run_place(uio: str, item: dict, six_cli: str, single_cli: str, targets: list[int],
              observe_ms: int, hold: int | None, dry_run: bool) -> tuple[bool, str]:
    """放置：先单独把 ID1（基座）转到放置侧、夹爪保持高位横摆，再六轴联动下放。

    10-24 实测：lift 后夹爪在高位，但 place 一次六轴把 ID1(+1021) 与 ID2(+900) 一起走，
    基座还没转到放置侧、ID2 就把臂伸下去，方块在高处横摆时撞到传送带边缘。拆成两段——
    先转 ID1（臂仍高，方块在空中横摆，不碰带），到位后再降 ID2/ID3 放置。ID6 由 hold 钉住。
    """
    parts = shlex.split(single_cli) + ["--uio", uio, "move",
                                       "--id", "1",
                                       "--target", str(targets[0]),
                                       "--speed-raw", str(item["speed_raw"][0]),
                                       "--time-raw", str(item["time_raw"][0]),
                                       "--tolerance", str(TRANSIT_TOLERANCE),
                                       "--execute"]
    if dry_run:
        first = "DRY_RUN " + shlex.join(parts)
        ok_first = True
    else:
        proc = subprocess.run(parts, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        first = out.strip().splitlines()[-1] if out.strip() else ""
        ok_first = proc.returncode == 0 and "RTCS_PL_G2_OK" in (proc.stdout or "")
    if not ok_first:
        return False, first
    ok, rest = run_step(uio, item, six_cli, single_cli, targets,
                        observe_ms, hold, "six", dry_run)
    return ok, first + "\n" + rest


def run_plan(plan: dict, uio: str, six_cli: str, single_cli: str, loops: int,
             observe_ms: int, transit: str, dry_run: bool,
             skip_steps: frozenset = frozenset(),
             stop_after: str | None = None,
             resume: str | None = None,
             grip_hold: int | None = None) -> int:
    """顺序执行 loops 轮六步；返回失败轮数。

    ``skip_steps`` 里的步整步跳过（只给 standby 用），跳过不改变成败判定。
    ``stop_after`` 命中某步后**在该步的六轴到位之后、夹爪动作之前**收尾退出，
    给动态拦截做"臂先到拦截位、夹爪保持张开、等外部触发再闭爪"用（见 docs/5.G5）。
    ``resume="close"`` 是它的后半段：臂已在拦截位，跳过 standby/approach/grasp 的移动，
    直接执行 grasp 步的夹爪闭合，然后 lift/place/retreat/exit 照常。
    """
    steps = plan["steps"]
    by_name = {s["name"]: s for s in steps}
    failures = 0
    # 时间基准点：CLOCK_MONOTONIC 跨进程同一时钟，与 server 的 ARM_CMD/SERVER_ACCEPT
    # 的 mono_ms 可直接相减 → 父子进程启动、载计划、校验这一段就能单独算出来。
    print("G3_T0 mono_ms=%.1f steps=%d" % (time.monotonic() * 1000.0, len(steps)))
    for cycle in range(1, loops + 1):
        print(f"G3_CYCLE start={cycle}/{loops}")
        cycle_start = time.monotonic()
        ok_cycle = True
        empty_grip = False           # 本次循环是否出现过"合到底但没夹住"
        closed_this_cycle = False    # 本轮是否真的执行过 close（决定末行 grip= 报什么）
        degraded = False             # stage 这一趟有没有"带伤收尾"（有则日志里标出来）
        # 夹爪接触位置；闭合后接管后续各步的 ID 6 目标。
        # --resume lift/place 时闭爪（和抬升）已在 server 侧做完，接触位置由 --grip-hold 传进来。
        hold: int | None = grip_hold if resume in ("lift", "place") else None
        for item in steps:
            name = item["name"]
            if name in skip_steps:
                # 不执行任何运动帧，也不碰 hold（standby 恒在循环首位，hold 此时为 None）
                print(f"G3_STEP name={name} result=SKIPPED elapsed_ms=0 "
                      "reason=direct_to_grasp_pose")
                continue
            targets = step_targets(item, hold)
            resume_skip = resume is not None and name in ("standby", "approach", "grasp")
            if resume_skip and name != "grasp":
                print(f"G3_STEP name={name} result=SKIPPED elapsed_ms=0 "
                      f"reason=resume_{resume}")
                continue
            if resume in ("lift", "place") and name == "grasp":
                # 闭爪已经由 server 直接调 C 单轴命令做完（省掉 880 ms 的 Python 启动），
                # 这里连夹爪动作也不再执行，直接从 lift（或 place）起。
                print(f"G3_STEP name={name} result=SKIPPED elapsed_ms=0 reason=resume_{resume}")
                continue
            if resume == "place" and name == "lift":
                # 抬升也已由 server 直接发六轴命令做完：这是"取消咬合后空档"的关键一刀，
                # 否则臂要被传送带拽着对抗 1.8 s。
                print(f"G3_STEP name={name} result=SKIPPED elapsed_ms=0 reason=resume_place")
                continue
            step_start = time.monotonic()
            if resume_skip:
                # 臂已在拦截位（上一条 dynamic_stage 走到的）：不动，直接进夹爪闭合。
                # 动一下就会把"提前量"算进去的时间又还给舵机，动态拦截就没有意义了。
                ok, out = True, "RESUME_AT_GRASP no_motion"
            # lift 走普通六轴联动，不拆两段（10-24 定案）：
            # 单轴 ID2 会越过竖直点(~1990)死区而静默停（实测 no_motion_ack），
            # 只有六轴联动让 ID2/ID3 一起动才穿得过；而"先 ID2 到底再 ID3"的两段式
            # 正是"ID3 猛然下降"观感的来源。六轴联动两者都解决。
            elif name == "place":
                ok, out = run_place(uio, item, six_cli, single_cli, targets,
                                    observe_ms, hold, dry_run)
            else:
                ok, out = run_step(uio, item, six_cli, single_cli, targets,
                                   observe_ms, hold, transit, dry_run,
                                   loose_id3=(stop_after == "grasp"))
            took = int((time.monotonic() - step_start) * 1000)
            if ok:
                if resume_skip:
                    # grasp 步在 --resume close 下没有运动，只走它的夹爪闭合；
                    # 报 SKIPPED 而不是 OK，否则日志会让人以为臂动过。
                    print(f"G3_STEP name={name} result=SKIPPED elapsed_ms=0 "
                          f"reason=resume_{resume}")
                else:
                    print(f"G3_STEP name={name} result=OK elapsed_ms={took}"
                          + (f" gripper_hold={hold}" if hold is not None else ""))
                    if dry_run and out.strip():
                        print("  " + out.strip())
                if stop_after and name == stop_after:
                    # 到了拦截位就停：**夹爪保持张开**，不执行该步的 close。
                    # 后面闭爪由外部（视觉触发）单独下发，本进程到此结束。
                    # hold 可能是 None（还没夹过），用局部变量而不是在 f-string 里写
                    # 三元表达式：双引号 f-string 的花括号里再写一对双引号，是 Python
                    # 3.12 才允许的语法（PEP 701）。板端 PetaLinux 是 3.10/3.11，
                    # 会直接 SyntaxError 整个文件，表现是"runner 231 ms 退出、
                    # 一行 G3_ 输出都没有"（2026-10-29 实际踩到）。
                    # 检查：python3 scripts/check_py_compat.py scripts/*.py
                    hold_text = "none" if hold is None else hold
                    print(f"G5_READY_AT step={name} targets={targets} "
                          f"gripper_open={targets[GRIPPER_AXIS - 1]} "
                          f"hold={hold_text} "
                          f"mono_ms={time.monotonic() * 1000.0:.1f}"
                          + (" degraded=true" if degraded else ""))
                    print(f"G3_CYCLE end={cycle} success=1 grip=open "
                          f"stopped_after={name}")
                    print(f"G3_CYCLE timing elapsed_ms="
                          f"{int((time.monotonic() - cycle_start) * 1000)}")
                    print(f"G3_RUN_SUMMARY cycles={cycle} failures={failures} "
                          f"aborted=0 stopped_after={name}")
                    return failures
            else:
                fault_text = fault_line(out)
                if stop_after:
                    # **stage 这一趟任何一步失败都不回位。**
                    # 这一趟的唯一目的是"停在拦截位张爪等着闭爪"；回位（exit）等于把这一轮
                    # 直接作废——现场看到的就是"刚要抓取就突然复位"。位置不准的后果只是
                    # 夹空（PC 侧 send_err 会显示），比整轮作废小得多；而且回位那次本身也可
                    # 能失败（日志里 grip=None 那种就是连 exit 也失败、直接 ABORT），
                    # 会把下一轮一起带坏。
                    print(f"G3_WARN {name} result=FAIL fault={fault_text}："
                          "stage 不回位（位置不准只会夹空）", file=sys.stderr)
                    degraded = True
                    if name == stop_after:
                        # 正好是"停在拦截位"那一步：直接按到位收尾，闭爪交给 PC。
                        print(f"G5_READY_AT step={name} targets={targets} "
                              f"gripper_open={targets[GRIPPER_AXIS - 1]} hold=none "
                              f"mono_ms={time.monotonic() * 1000.0:.1f} degraded=true")
                        print(f"G3_CYCLE end={cycle} success=1 grip=open "
                              f"stopped_after={name}")
                        print(f"G3_CYCLE timing elapsed_ms="
                              f"{int((time.monotonic() - cycle_start) * 1000)}")
                        print(f"G3_RUN_SUMMARY cycles={cycle} failures={failures} "
                              f"aborted=0 stopped_after={name}")
                        return failures
                    continue          # 其它步失败：跳过它的收尾，继续往下一步走
                print(f"G3_STEP name={name} result=FAIL fault={fault_text}")
                ok_cycle = False
                # 手里还夹着东西就先松爪，再回位。
                # 2026-11-03 现场：多件在线上时，搬运段偶尔失败，程序直接走 exit 复位，
                # 方块被**带回**虎口里；下一轮于是从"虎口已经塞着东西"开始——抓取乱、
                # 放置像被跳过、越来越差。先张爪把件放下（就地放），再复位，链条才断得干净。
                if hold is not None:
                    release = (by_name.get("place") or {}).get("gripper") or {}
                    if release.get("command") == "open":
                        rel_ok, rel_detail, rel_pos = run_gripper(
                            uio, release, single_cli, dry_run)
                        print(f"G3_STEP name=release_after_fail result={rel_detail}"
                              + (f" position={rel_pos}" if rel_pos is not None else ""))
                        if rel_ok:
                            hold = None        # 已经松开：复位时不要再把 ID6 钉在接触位
                if name != "exit":
                    exit_item = by_name["exit"]
                    exit_ok, exit_out = run_step(
                        uio, exit_item, six_cli, single_cli,
                        step_targets(exit_item, hold), observe_ms, hold,
                        transit, dry_run)
                    if exit_ok:
                        print("G3_STEP name=exit result=OK recovery=true")
                    else:
                        print(f"G3_STEP name=exit result=FAIL recovery=false "
                              f"fault={fault_line(exit_out)}")
                        print("G3_ABORT exit_recovery_failed")
                        failures += 1
                        print(f"G3_RUN_SUMMARY cycles={cycle} failures={failures} aborted=1")
                        return failures
                break

            action = item.get("gripper")
            if action is None:
                continue
            grasp_start = time.monotonic()
            grasp_ok, detail, position = run_gripper(uio, action, single_cli, dry_run)
            grasp_took = int((time.monotonic() - grasp_start) * 1000)
            if grasp_ok:
                print(f"G3_STEP name={name}.gripper result={detail} elapsed_ms={grasp_took}"
                      + (f" position={position}" if position is not None else ""))
                if detail == "EMPTY":
                    # 不判失败、不中止（用户要求不做硬门禁），但必须显式说出来：
                    # 这一轮八步都会"成功"，可方块根本没被夹住，统计口径会全错。
                    empty_grip = True
                    print(f"G3_WARN grasp.gripper=EMPTY position={position} "
                          f"target={action.get('target_count')} "
                          f"(合到底没有接触位：这一轮没夹到东西)")
                if dry_run:
                    print("  DRY_RUN " + shlex.join(
                        build_single_axis_args(uio, action, single_cli)))
                if action.get("command") == "close":
                    closed_this_cycle = True
                    # 接触位置接管保持；读不到就退回命令目标并明确标注，不静默。
                    hold = position if position is not None else action["target_count"]
                    if position is None and not dry_run:
                        print(f"G3_WARN gripper_hold_from_command target={hold}")
                else:
                    hold = None
            else:
                print(f"G3_STEP name={name}.gripper result=FAIL fault={detail}")
                ok_cycle = False
                exit_item = by_name["exit"]
                exit_ok, exit_out = run_step(
                    uio, exit_item, six_cli, single_cli,
                    step_targets(exit_item, hold), observe_ms, hold,
                    transit, dry_run)
                if exit_ok:
                    print("G3_STEP name=exit result=OK recovery=true")
                else:
                    print(f"G3_STEP name=exit result=FAIL recovery=false "
                          f"fault={fault_line(exit_out)}")
                    print("G3_ABORT exit_recovery_failed")
                    failures += 1
                    print(f"G3_RUN_SUMMARY cycles={cycle} failures={failures} aborted=1")
                    return failures
                break
        # dry-run 下夹爪根本没动，写 contact 会误导人（首连链路测试时最容易看错）。
        # 同理：**没闭过爪就不能报 contact**。2026-11-03 踩到：dynamic_stage 用
        # --stop-after grasp 收尾时根本不闭爪，可这一行照旧写 contact，PC 侧
        # 打出来的就是 "G5_STAGE ok=False grip=contact" 这种不可能的组合，看着像回包错位。
        if dry_run:
            grip = "dry_run"
        elif not closed_this_cycle:
            grip = "open"
        else:
            grip = "empty" if empty_grip else "contact"
        print(f"G3_CYCLE end={cycle} success={1 if ok_cycle else 0} grip={grip}")
        print(f"G3_CYCLE timing elapsed_ms={int((time.monotonic() - cycle_start) * 1000)}")
        if not ok_cycle:
            failures += 1
    print(f"G3_RUN_SUMMARY cycles={loops} failures={failures} aborted=0")
    return failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--uio", default="/dev/uio0")
    parser.add_argument("--six-cli", default="rtcs-pl-g2-six",
                        help="move-six 可执行路径（回归时注入 mock）")
    parser.add_argument("--single-cli", default="rtcs-pl-g2",
                        help="夹爪单轴 move 可执行路径（回归时注入 mock）")
    parser.add_argument("--observe-ms", type=int, default=DEFAULT_OBSERVE_MS,
                        metavar="1000..10000",
                        help="六轴到位观察期；长杆大位移步需要更长窗口，默认 8000")
    parser.add_argument("--transit", choices=("six", "per-axis"), default="six",
                        help="搬运方式：six=六轴同步（默认）；per-axis=逐轴单舵机，"
                             "各关节解耦，绕开六轴联动时的过中心死区（慢一些）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="跑一轮六步（默认）")
    group.add_argument("--loop", type=int, metavar="N", help="跑 N 轮")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令不执行")
    parser.add_argument("--grasp-xy", type=lambda s: tuple(float(v) for v in s.split(",")),
                        metavar="X,Y", help="视觉抓：用平面坐标覆盖抓取点（单位 mm）")
    parser.add_argument("--standby", choices=("auto", "keep", "skip"), default="auto",
                        help="standby 步处理：auto=给了 --grasp-xy 就跳过（默认，省一趟往返）；"
                             "keep=照旧先到静态 standby；skip=强制跳过")
    parser.add_argument("--teaching-table", type=Path,
                        help="--grasp-xy 需要的示教点表（见 grasp_point_map.py）")
    parser.add_argument("--stop-after", choices=("grasp",), default=None,
                        help="在该步六轴到位之后、夹爪动作之前收尾退出，夹爪保持张开。"
                             "动态拦截的'提前就位'用：臂先守在拦截点，闭爪由外部触发单独下发。"
                             "当前只支持 grasp（grasp 步的夹爪动作是 close，必须跳过）")
    parser.add_argument("--resume", choices=("close", "lift", "place"), default=None,
                        help="从该动作接着跑：close=臂已在拦截位，跳过 standby/approach/grasp "
                             "的移动，直接闭爪，然后 lift/place/retreat/exit；"
                             "lift=连闭爪也跳过（闭爪已由 server 直接调 C 单轴命令做完）；"
                             "place=连 lift 也跳过（lift 也已由 server 直接发六轴命令做完）。"
                             "lift/place 都要给 --grip-hold")
    parser.add_argument("--grip-hold", type=int, default=None,
                        help="--resume lift/place 时夹爪的保持位置（fast-close 读到的接触位置）")
    parser.add_argument("--grasp-id2-offset", type=int, default=0,
                        help="给 approach/grasp 的 ID2 目标加一个偏移（现场指定，不是推算）。"
                             "负值=把夹取点抬高一点，让上夹臂合拢时把方块掀起一角，"
                             "减少与传送带的接触面（动态抓取时的摩擦对抗用）")
    args = parser.parse_args(argv)

    if args.loop is not None and args.loop < 1:
        parser.error("--loop N 必须 >= 1")
    if args.grasp_xy is not None and args.teaching_table is None:
        parser.error("--grasp-xy 需要 --teaching-table")
    if args.stop_after is not None and args.resume is not None:
        parser.error("--stop-after 与 --resume 不能同时给：前者收尾、后者接着跑，语义互斥")
    if args.resume in ("lift", "place") and args.grip_hold is None:
        parser.error("--resume lift/place 需要 --grip-hold（夹爪的接触位置，来自 fast-close 的读数）")
    if args.teaching_table is not None and args.grasp_xy is None:
        parser.error("--teaching-table 只在 --grasp-xy 时使用")
    if args.observe_ms < 1000 or args.observe_ms > 10000 or args.observe_ms % 100:
        parser.error("--observe-ms 必须是 1000..10000 之间的 100 的倍数")

    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        # 门禁：六步顺序/越界/preflight/夹爪动作；真跑时还要求每步是实测值
        g3_offline_plan.validate(plan, require_measured=not args.dry_run)
        if args.grasp_xy is not None:
            apply_grasp_point(plan, args.grasp_xy[0], args.grasp_xy[1],
                              args.teaching_table)
        if args.grasp_id2_offset:
            # 现场指定的偏移（不是推算）：负值把夹取点抬高一点，上夹臂合拢时方块被掀起
            # 一角、与传送带的接触面变小，动态抓取时那 0.5~1 s 的摩擦对抗会明显减弱。
            for item in plan["steps"]:
                if item["name"] in GRASP_STEPS:
                    item["target_count"][1] += args.grasp_id2_offset
            print("G3_INFO grasp ID2 offset %+d（现场指定）：approach/grasp ID2 已调整"
                  % args.grasp_id2_offset)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"G3_PLAN_REJECTED {error}", file=sys.stderr)
        return 1

    loops = args.loop if args.loop is not None else 1
    skip_steps: frozenset = frozenset()
    if args.standby == "skip" or (args.standby == "auto" and args.grasp_xy is not None):
        skip_steps = frozenset(SKIPPABLE_STEPS)
        print("G3_INFO skip standby: first motion goes straight from the reset/exit pose "
              f"to the grasp pose (--standby {args.standby})")
        # 只告警不拦截：直达标定位省一趟 985 ms 往返，但第一段运动是"自高位直接落到
        # 抓取点"，与旧流程 exit->standby 的落差相同、水平落点不同，首次请目视确认不扫件。
        print("G3_WARN verify the sweep visually on the first run: reset pose -> grasp pose "
              "is a single six-axis interpolation", file=sys.stderr)
    failures = run_plan(plan, args.uio, args.six_cli, args.single_cli, loops,
                        args.observe_ms, args.transit, args.dry_run, skip_steps,
                        args.stop_after, args.resume, args.grip_hold)
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
