#!/usr/bin/env python3
"""G3 状态机编排层：读已确认的工位计划，顺序执行六步，故障留痕不锁死。

软状态机（PS 侧任务编排）。每步 = 一次 ``move-six``（subprocess 调用 rtcs-pl-g2-six）。
真正的组帧、总线时序、限位门禁全在 PL；本程序只负责"顺序 + 每步成败判定 + 故障留痕"。

抓取点参数化：approach/grasp/lift 三步随 (x, y) 变化的是 ID 1-3；给定 ``--grasp-xy``
时用 :mod:`grasp_point_map` 把平面坐标映射成这三步的目标，盲抓（不给坐标）则用计划里
的固定示教点。同一份程序两种喂点方式。

用法：
  # 盲抓：跑一遍六步
  python3 scripts/g3_station_runner.py config/g3_station_plan.json --uio /dev/uio0 --once
  # 盲抓：连续 10 轮（11.04 兜底视频）
  python3 scripts/g3_station_runner.py config/g3_station_plan.json --uio /dev/uio0 --loop 10
  # 只打印命令不执行（人工审阅）
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
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import g3_offline_plan  # noqa: E402  复用其门禁校验
import grasp_point_map  # noqa: E402  抓取点参数化的几何层

STEPS = ("standby", "approach", "grasp", "lift", "place", "exit")
# 随平面坐标 (x,y) 变化的三步；ID 1-3 由映射覆盖，ID 4-6 保留该步固定姿态。
GRASP_STEPS = ("approach", "grasp", "lift")


def build_move_six_args(uio: str, item: dict, six_cli: str) -> list[str]:
    """把一步工位计划翻译成 move-six 命令参数。six_cli 可带参数（如
    ``python3 mock.py``），用 shlex 拆分。"""
    parts = shlex.split(six_cli) + ["--uio", uio, "move-six"]
    for i in range(6):
        parts += ["--axis",
                  f"{i + 1}:{item['target_count'][i]}:{item['speed_raw'][i]}:{item['time_raw'][i]}"]
    parts.append("--execute")
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


def run_step(uio: str, item: dict, six_cli: str, dry_run: bool) -> tuple[bool, str]:
    """执行一步，返回 (是否成功, 输出文本)。"""
    parts = build_move_six_args(uio, item, six_cli)
    cmdline = shlex.join(parts)
    if dry_run:
        return True, "DRY_RUN " + cmdline
    proc = subprocess.run(parts, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode == 0 and "RTCS_PL_G2_SIX_OK" in (proc.stdout or "")
    return ok, output


def fault_line(output: str) -> str:
    """从 move-six 输出里抽出故障摘要，用于留痕。"""
    for line in output.splitlines():
        if "ERR g2_six_fault=" in line:
            return line.strip()
    return "no_motion_ack"


def run_plan(plan: dict, uio: str, six_cli: str, loops: int, dry_run: bool) -> int:
    """顺序执行 loops 轮六步；返回失败轮数。"""
    steps = plan["steps"]
    by_name = {s["name"]: s for s in steps}
    failures = 0
    for cycle in range(1, loops + 1):
        print(f"G3_CYCLE start={cycle}/{loops}")
        ok_cycle = True
        recovered = False
        for idx, item in enumerate(steps):
            name = item["name"]
            ok, out = run_step(uio, item, six_cli, dry_run)
            if ok:
                print(f"G3_STEP name={name} result=OK")
                if dry_run and out.strip():
                    print("  " + out.strip())
            else:
                print(f"G3_STEP name={name} result=FAIL fault={fault_line(out)}")
                ok_cycle = False
                # 故障不锁死：非 exit 步失败，尝试 exit 安全回位后结束本轮。
                if name != "exit":
                    exit_ok, exit_out = run_step(uio, by_name["exit"], six_cli, dry_run)
                    if exit_ok:
                        print("G3_STEP name=exit result=OK recovery=true")
                        recovered = True
                    else:
                        print(f"G3_STEP name=exit result=FAIL recovery=false "
                              f"fault={fault_line(exit_out)}")
                        print("G3_ABORT exit_recovery_failed")
                        failures += 1
                        print(f"G3_RUN_SUMMARY cycles={cycle} failures={failures} aborted=1")
                        return failures
                break
        print(f"G3_CYCLE end={cycle} success={1 if ok_cycle else 0}")
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

    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        g3_offline_plan.validate(plan)  # 门禁：ID5 放行/越界/preflight/六步顺序
        if args.grasp_xy is not None:
            apply_grasp_point(plan, args.grasp_xy[0], args.grasp_xy[1],
                              args.teaching_table)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"G3_PLAN_REJECTED {error}", file=sys.stderr)
        return 1

    loops = args.loop if args.loop is not None else 1
    failures = run_plan(plan, args.uio, args.six_cli, loops, args.dry_run)
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
