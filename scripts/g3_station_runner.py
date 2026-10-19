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

STEPS = ("standby", "approach", "grasp", "lift", "place", "exit")
# 随平面坐标 (x,y) 变化的三步；ID 1-3 由映射覆盖，ID 4-6 保留该步固定姿态。
GRASP_STEPS = ("approach", "grasp", "lift")
GRIPPER_AXIS = 6
# 夹爪保持时给足容差：物块顶着夹爪，实测位置与命令目标天然有几百 count 的差。
GRIPPER_HOLD_TOLERANCE = 100
DEFAULT_OBSERVE_MS = 8000
# 舵机 ERROR 的 bit5 是过载电压/电流保护，夹住物块时出现属正常工况，不是故障。
SERVO_OVERLOAD_BIT = 0x20


def step_targets(item: dict, hold: int | None) -> list[int]:
    """该步真正下发的六轴目标；夹爪处于保持态时用接触位置覆盖计划值。"""
    targets = list(item["target_count"])
    if hold is not None:
        targets[GRIPPER_AXIS - 1] = hold
    return targets


def build_move_six_args(uio: str, item: dict, six_cli: str, targets: list[int],
                        observe_ms: int, hold: int | None) -> list[str]:
    """把一步工位计划翻译成 move-six 命令参数。six_cli 可带参数（如
    ``python3 mock.py``），用 shlex 拆分。"""
    parts = shlex.split(six_cli) + ["--uio", uio, "move-six"]
    for i in range(6):
        parts += ["--axis",
                  f"{i + 1}:{targets[i]}:{item['speed_raw'][i]}:{item['time_raw'][i]}"]
    if hold is not None:
        parts += ["--tolerance", f"{GRIPPER_AXIS}:{GRIPPER_HOLD_TOLERANCE}"]
    parts += ["--observe-ms", str(observe_ms), "--execute"]
    return parts


def build_single_axis_args(uio: str, action: dict, single_cli: str) -> list[str]:
    """夹爪开合翻译成单轴 move 命令（rtcs-pl-g2）。"""
    axis = action.get("actuator_id", GRIPPER_AXIS)
    parts = shlex.split(single_cli) + ["--uio", uio, "move",
                                       "--id", str(axis),
                                       "--target", str(action["target_count"]),
                                       "--speed-raw", str(action.get("speed_raw", 500)),
                                       "--time-raw", str(action.get("time_raw", 10)),
                                       "--execute"]
    return parts


def apply_grasp_point(plan: dict, x_mm: float, y_mm: float, table_path: Path) -> None:
    """用映射坐标覆盖 approach/grasp/lift 三步的 ID 1-3 目标（就地改 plan）。"""
    table = grasp_point_map.load_table(table_path)
    for item in plan["steps"]:
        if item["name"] not in GRASP_STEPS:
            continue
        fixed_pose = item["target_count"][3:6]  # ID 4-6 保留该步固定姿态
        six = grasp_point_map.map_grasp(x_mm, y_mm, table, fixed_pose, method="nearest")
        item["target_count"][0:3] = six[0:3]


def run_move_six(uio: str, item: dict, six_cli: str, targets: list[int],
                 observe_ms: int, hold: int | None, dry_run: bool) -> tuple[bool, str]:
    """执行一步六轴运动，返回 (是否成功, 输出文本)。"""
    parts = build_move_six_args(uio, item, six_cli, targets, observe_ms, hold)
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
             dry_run: bool) -> tuple[bool, str]:
    """夹爪处于保持态时逐轴搬运（ID6 过载不进 move-six），否则用六轴同步。"""
    if hold is not None:
        return run_per_axis(uio, item, single_cli, targets, dry_run)
    return run_move_six(uio, item, six_cli, targets, observe_ms, hold, dry_run)


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
    """
    position = observed_gripper_position(output)
    if "RTCS_PL_G2_OK" in output:
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
    for i in range(5):
        parts = shlex.split(single_cli) + ["--uio", uio, "move",
                                           "--id", str(i + 1),
                                           "--target", str(targets[i]),
                                           "--speed-raw", str(item["speed_raw"][i]),
                                           "--time-raw", str(item["time_raw"][i]),
                                           "--execute"]
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


def run_plan(plan: dict, uio: str, six_cli: str, single_cli: str, loops: int,
             observe_ms: int, dry_run: bool) -> int:
    """顺序执行 loops 轮六步；返回失败轮数。"""
    steps = plan["steps"]
    by_name = {s["name"]: s for s in steps}
    failures = 0
    for cycle in range(1, loops + 1):
        print(f"G3_CYCLE start={cycle}/{loops}")
        cycle_start = time.monotonic()
        ok_cycle = True
        hold: int | None = None      # 夹爪接触位置；闭合后接管后续各步的 ID 6 目标
        for item in steps:
            name = item["name"]
            targets = step_targets(item, hold)
            ok, out = run_step(uio, item, six_cli, single_cli, targets,
                               observe_ms, hold, dry_run)
            if ok:
                print(f"G3_STEP name={name} result=OK"
                      + (f" gripper_hold={hold}" if hold is not None else ""))
                if dry_run and out.strip():
                    print("  " + out.strip())
            else:
                print(f"G3_STEP name={name} result=FAIL fault={fault_line(out)}")
                ok_cycle = False
                if name != "exit":
                    exit_item = by_name["exit"]
                    exit_ok, exit_out = run_step(
                        uio, exit_item, six_cli, single_cli,
                        step_targets(exit_item, hold), observe_ms, hold, dry_run)
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
            grasp_ok, detail, position = run_gripper(uio, action, single_cli, dry_run)
            if grasp_ok:
                print(f"G3_STEP name={name}.gripper result={detail}"
                      + (f" position={position}" if position is not None else ""))
                if dry_run:
                    print("  DRY_RUN " + shlex.join(
                        build_single_axis_args(uio, action, single_cli)))
                if action.get("command") == "close":
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
                    step_targets(exit_item, hold), observe_ms, hold, dry_run)
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
        print(f"G3_CYCLE end={cycle} success={1 if ok_cycle else 0}")
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
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="跑一轮六步（默认）")
    group.add_argument("--loop", type=int, metavar="N", help="跑 N 轮")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令不执行")
    parser.add_argument("--grasp-xy", type=lambda s: tuple(float(v) for v in s.split(",")),
                        metavar="X,Y", help="视觉抓：用平面坐标覆盖抓取点（单位 mm）")
    parser.add_argument("--teaching-table", type=Path,
                        help="--grasp-xy 需要的示教点表（见 grasp_point_map.py）")
    args = parser.parse_args(argv)

    if args.loop is not None and args.loop < 1:
        parser.error("--loop N 必须 >= 1")
    if args.grasp_xy is not None and args.teaching_table is None:
        parser.error("--grasp-xy 需要 --teaching-table")
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
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"G3_PLAN_REJECTED {error}", file=sys.stderr)
        return 1

    loops = args.loop if args.loop is not None else 1
    failures = run_plan(plan, args.uio, args.six_cli, args.single_cli, loops,
                        args.observe_ms, args.dry_run)
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
