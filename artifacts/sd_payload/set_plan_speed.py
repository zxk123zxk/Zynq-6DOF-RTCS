#!/usr/bin/env python3
"""把工位计划里的舵机速度（`speed_raw`）批量改成同一个值。

为什么要有这个工具：`config/g3_station_plan.json` 里 7 步 × 6 轴 = 42 个 speed 数字，
外加 2 个夹爪动作；手改一定会漏、也一定会把 `time_raw` 碰坏。速度是"整机一个旋钮"
的参数，应该一条命令改完、改完立刻能自查。

用法：
    # 只看改成什么样（不落盘）
    python scripts/set_plan_speed.py --six 1000 --gripper 1000

    # 真改（会先写一份 .bak）
    python scripts/set_plan_speed.py --six 1000 --gripper 1000 --apply

    # 只改某几步（其余保持）
    python scripts/set_plan_speed.py --six 1200 --step lift=1200 --step place=1200 --apply

    # 只改夹爪
    python scripts/set_plan_speed.py --gripper 1000 --apply

**改完必须重测时序**：速度变了，`docs/5.G5` 的 `move_to_pose_ms` 与 `advance_ms` 都要按实测重填，
否则动态抓取的提前量会系统性偏掉（日志里的 `G5_WARN 臂到位比计划…` 就是提示）。
夹爪速度上限另有一条：`MAX_GRIPPER_SPEED`（见下），超过会被抬回去并告警。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "config" / "g3_station_plan.json"
LIMITS = ROOT / "config" / "g2_measured_limits.toml"
# 六轴与夹爪共用的硬件上限（HX-30HM / PL 拒绝 >1500）。
SPEED_MAX = 1500
# 夹爪的实测上限。动态闭爪用 1500 是走 server 的 fast-close（另一条路径，不读计划），
# 计划里的这个值只影响**静态**七步的夹爪开合。
MAX_GRIPPER_SPEED = 1500


def load_limit_max() -> int:
    """从限位正本读 speed_raw_max；读不到就用 1500（与 PL 常量一致）。"""
    try:
        for line in LIMITS.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "speed_raw_max":
                return int(value.strip())
    except (OSError, ValueError):
        pass
    return SPEED_MAX


def collect(plan: dict) -> list[tuple[str, str, int]]:
    """列出所有速度项：(步骤名, 类别, 当前值)。类别是 six / gripper。"""
    rows = []
    for step in plan["steps"]:
        speeds = step.get("speed_raw")
        if isinstance(speeds, list):
            for value in speeds:
                rows.append((step["name"], "six", value))
        gripper = step.get("gripper")
        if isinstance(gripper, dict) and "speed_raw" in gripper:
            rows.append((step["name"], "gripper", gripper["speed_raw"]))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--six", type=int, help="六轴所有步骤统一改成这个速度")
    parser.add_argument("--gripper", type=int, help="夹爪开合统一改成这个速度")
    parser.add_argument("--step", action="append", default=[], metavar="NAME=SPEED",
                        help="只改某一步的六轴速度，可重复：--step lift=1200")
    parser.add_argument("--apply", action="store_true", help="真的写回（默认只打印）")
    args = parser.parse_args(argv)

    hard_max = load_limit_max()
    for value, label in ((args.six, "--six"), (args.gripper, "--gripper")):
        if value is None:
            continue
        if not 1 <= value <= hard_max:
            parser.error("%s 必须在 1..%d（PL 与舵机协议上限）" % (label, hard_max))
    if args.gripper is not None and args.gripper > MAX_GRIPPER_SPEED:
        print("WARN --gripper %d 超过夹爪限值 %d，按 %d 处理"
              % (args.gripper, MAX_GRIPPER_SPEED, MAX_GRIPPER_SPEED), file=sys.stderr)
        args.gripper = MAX_GRIPPER_SPEED

    per_step: dict[str, int] = {}
    for item in args.step:
        name, _, value = item.partition("=")
        if not name or not value.isdigit():
            parser.error("--step 要写成 NAME=SPEED，收到 %r" % item)
        if not 1 <= int(value) <= hard_max:
            parser.error("--step %s 的速度必须在 1..%d" % (name, hard_max))
        per_step[name.strip()] = int(value)

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    before = collect(plan)
    if not args.six and args.gripper is None and not per_step:
        parser.error("至少给一个：--six / --gripper / --step")

    for step in plan["steps"]:
        name = step["name"]
        if args.six is not None and isinstance(step.get("speed_raw"), list):
            step["speed_raw"] = [args.six] * len(step["speed_raw"])
        if name in per_step and isinstance(step.get("speed_raw"), list):
            step["speed_raw"] = [per_step[name]] * len(step["speed_raw"])
        gripper = step.get("gripper")
        if args.gripper is not None and isinstance(gripper, dict) and "speed_raw" in gripper:
            gripper["speed_raw"] = args.gripper
    after = collect(plan)

    # 逐项对比表：只有真的变了才打，便于"我到底改了哪几处"一眼确认
    print("%-10s %-8s %6s -> %6s" % ("步骤", "类别", "旧", "新"))
    changed = 0
    for (name, kind, old), (_n, _k, new) in zip(before, after):
        if old != new:
            print("%-10s %-8s %6d -> %6d" % (name, kind, old, new))
            changed += 1
    print("共 %d 处%s" % (changed, "" if changed else "（没有变化）"))

    if not args.apply:
        print("DRY_RUN 未写回。加 --apply 才落盘")
        return 0
    if not changed:
        return 0
    backup = args.plan.with_suffix(args.plan.suffix + ".bak")
    shutil.copy2(args.plan, backup)
    # write_bytes：Windows 上 write_text 会把 LF 转 CRLF，板端比对会出现假差异
    text = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    args.plan.write_bytes(text.encode("utf-8"))
    print("WROTE %s（备份 %s）" % (args.plan, backup.name))
    print("NEXT 重新打包并校验：bash scripts/stage_sd_payload.sh")
    print("NEXT 速度变了就重测时序：动态的 move_to_pose_ms / advance_ms 见 config/g5_dynamic.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
