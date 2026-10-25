#!/usr/bin/env python3
"""把一个示教点追加进抓取示教表（板端执行，边看边录，不用手编 JSON）。

用法（板端，臂已摆到该点、夹爪正好包住物块时）：

    sudo python3 scripts/teach_add_point.py --x-mm 60 --y-mm 40

它会：
  1. 读六轴当前值（`rtcs-pl-g2-six diagnose`，只读，不发运动帧）；
  2. 取 ID 1-5 作为该点的姿态目标（`--axes 3` 则只取 ID 1-3，旧格式）；
  3. 五轴模式只校验 ID6 与 grasp 步的开度是否一致（ID4/ID5 反正会被插值覆盖）；
     三轴模式仍校验 ID4-6 是否与 grasp 步的固定姿态一致（不一致只告警，不拒绝）；
  4. 追加/覆盖到 `config/grasp_teaching_table.json`，按 x_mm 排序。

**为什么默认五轴**：ID4/ID5 是腕部姿态。教点时臂停在什么腕姿，运行时就该是什么腕姿。
旧的三轴格式让运行时用计划里的固定 ID4/ID5，实测下来这和教点时的腕姿能差 150~250
count（10-22 实测），夹爪会以一个倾斜姿态落下去。ID6 是夹爪开度，属执行器指令，
闭合后由接触位置接管，所以**永远不进表**。

`(x_mm, y_mm)` 必须与视觉 `config/calibration.json` 同一坐标系：
**原点 = 传送带左下角，+x 沿传送带长度方向，+y 沿宽度方向**。

为什么要这个脚本：手编 JSON 容易漏字段、写错 ID 顺序，而且终端里的多行
heredoc 曾被粘贴流截断过（10-20 事故）。脚本只有一个调用点，出错面小。
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TABLE = ROOT / "config" / "grasp_teaching_table.json"
PLAN = ROOT / "config" / "g3_station_plan.json"

# 三轴模式下用来比对"计划固定姿态"的非位置轴。五轴模式下 ID4/ID5 进表，只校验 ID6。
FIXED_AXES = (4, 5, 6)


def read_positions(six_cli: str, uio: str) -> dict[int, int]:
    """调 diagnose 取六轴当前值。只读命令，不产生任何运动。

    解析刻意做得宽松：只要一行里同时有 ``id=N`` 和 ``position_raw=M`` 就收，
    不要求前面的 ``diagnose `` 前缀、也不要求后面一定跟 servo_error。
    CLI 的输出格式在不同版本间有过微调，正则咬太死会直接读不到（10-21 实际踩过）。
    """
    parts = shlex.split(six_cli) + ["--uio", uio, "diagnose"]
    proc = subprocess.run(parts, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(output.strip().splitlines()[:10]) or "(空)"

    if not output.strip():
        sys.exit(f"DIAGNOSE_NO_OUTPUT rc={proc.returncode} cmd={shlex.join(parts)}\n"
                 "  命令本身没产出任何输出。先手动跑一次：\n"
                 f"    sudo {shlex.join(parts)}\n"
                 "  若提示找不到命令，用 --six-cli 指定绝对路径（which rtcs-pl-g2-six 查）。")

    positions, errors = {}, {}
    for line in output.splitlines():
        if "position_raw=" not in line:
            continue
        m_id = re.search(r"id=(\d+)", line)
        m_pos = re.search(r"position_raw=(\d+)", line)
        if not (m_id and m_pos):
            continue
        axis = int(m_id.group(1))
        if not 1 <= axis <= 6 or axis in positions:
            continue
        positions[axis] = int(m_pos.group(1))
        m_err = re.search(r"servo_error=0x([0-9a-fA-F]{1,2})", line)
        errors[axis] = int(m_err.group(1), 16) if m_err else 0

    if "RTCS_PL_G2_SIX_DIAG" not in output and not positions:
        sys.exit(f"DIAGNOSE_FAILED: 命令没成功（rc={proc.returncode}）。原始输出：\n{tail}")
    if set(positions) != set(range(1, 7)):
        sys.exit(f"DIAGNOSE_INCOMPLETE: 只读到 {sorted(positions)}，缺 "
                 f"{sorted(set(range(1, 7)) - set(positions))}。原始输出前 10 行：\n{tail}")

    bad = {axis: hex(err) for axis, err in errors.items() if err}
    if bad:
        print(f"TEACH_WARN servo_error 非零 {bad}——该点舵机有故障，录进去也没法复现",
              file=sys.stderr)
    return positions


def grasp_fixed_pose() -> list[int] | None:
    """从工位计划里取 grasp 步的 ID 4-6，用于比对姿态/开度。取不到就返回 None。"""
    try:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        item = next(s for s in plan["steps"] if s["name"] == "grasp")
        return list(item["target_count"][3:6])
    except Exception:
        return None


def load_table(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--x-mm", type=float, required=True,
                        help="传送带坐标系 x（原点=左下角，+x 沿带长）")
    parser.add_argument("--y-mm", type=float, required=True,
                        help="传送带坐标系 y（+y 沿带宽）")
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--uio", default="/dev/uio0")
    parser.add_argument("--six-cli", default="rtcs-pl-g2-six")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写表")
    parser.add_argument("--axes", type=int, choices=(3, 5), default=5,
                        help="录几轴：5=ID1-5 全部进表（默认，推荐）；"
                             "3=只录 ID1-3（旧格式，要求各点腕姿一致）")
    parser.add_argument("--lift", action="store_true",
                        help="录该点的**抬升**姿态（lift_targets），不是抓取姿态")
    args = parser.parse_args()

    pos = read_positions(args.six_cli, args.uio)
    axes = tuple(range(1, args.axes + 1))
    targets = [pos[axis] for axis in axes]
    table = load_table(args.table)

    if args.lift:
        # 抬升姿态与抓取姿态的关系取决于基座角，是非线性的，只能逐点实测。
        match = next((p for p in table
                      if abs(p["x_mm"] - args.x_mm) < 1e-6 and abs(p["y_mm"] - args.y_mm) < 1e-6),
                     None)
        if match is None:
            sys.exit(f"LIFT_NEEDS_POINT: 表里没有 ({args.x_mm}, {args.y_mm}) 这个抓取点。\n"
                     "  先不带 --lift 录一次抓取姿态：\n"
                     f"    sudo python3 scripts/teach_add_point.py "
                     f"--x-mm {args.x_mm} --y-mm {args.y_mm}")
        match["lift_targets"] = targets
        print(f"TEACH_LIFT {json.dumps(match, ensure_ascii=False)}")
        if args.dry_run:
            print("TEACH_DRY_RUN 未写表")
            return 0
        args.table.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        print(f"TEACH_LIFT_OK points={len(table)} file={args.table}")
        return 0

    want = grasp_fixed_pose()
    if want is not None:
        if args.axes == 5:
            # 五轴表里 ID4/ID5 会被插值覆盖，只有 ID6（夹爪开度）仍取计划值，
            # 所以只校验 ID6；ID4/ID5 与计划不同是**正常的**，不该告警。
            if abs(pos[6] - want[2]) > 30:
                print(f"TEACH_WARN 点 {args.x_mm},{args.y_mm} 的 ID6={pos[6]} 与 grasp 步"
                      f"开度 {want[2]} 偏差 >30：运行时夹爪按计划值张开，"
                      "若这里有偏差，接近时可能蹭到物块。", file=sys.stderr)
        else:
            got = [pos[axis] for axis in FIXED_AXES]
            drift = [f"ID{a}:{g}≠{wi}" for a, g, wi in zip(FIXED_AXES, got, want)
                     if abs(g - wi) > 30]
            if drift:
                print("TEACH_WARN 点 {x},{y} 的 ID4-6 与 grasp 步固定姿态偏差 >30：".format(
                    x=args.x_mm, y=args.y_mm) + " ".join(drift)
                    + "\n  三轴表下 ID4-6 一律取计划值，只有各点腕姿一致时插值才成立；"
                      "要么把臂摆到 grasp 步的姿态再录，要么改用 --axes 5。", file=sys.stderr)

    point = {"x_mm": float(args.x_mm), "y_mm": float(args.y_mm), "targets": targets}
    previous = next((p for p in table
                     if abs(p["x_mm"] - args.x_mm) < 1e-6 and abs(p["y_mm"] - args.y_mm) < 1e-6),
                    None)
    if previous and "lift_targets" in previous:
        point["lift_targets"] = previous["lift_targets"]   # 重录抓取姿态时保留已录的抬升姿态
    kept = [p for p in table
            if not (abs(p["x_mm"] - args.x_mm) < 1e-6 and abs(p["y_mm"] - args.y_mm) < 1e-6)]
    # 轴数不一致时整表作废：三轴与五轴混用无法消歧（运行时 load_table 也会拒绝）。
    mixed = {len(p["targets"]) for p in kept} - {len(targets)}
    if mixed:
        sys.exit(f"TEACH_AXIS_MISMATCH 表里已有 {sorted(mixed)} 轴的点，现在要写 "
                 f"{len(targets)} 轴的。先统一：清空重录，或本次加 --axes {sorted(mixed)[0]}")
    kept.append(point)
    kept.sort(key=lambda p: (p["x_mm"], p["y_mm"]))

    line = json.dumps(point, ensure_ascii=False)
    print(f"TEACH_POINT {line}   ({args.axes}轴, 实测 ID6 = {pos[6]})")
    if args.dry_run:
        print("TEACH_DRY_RUN 未写表")
        return 0

    args.table.parent.mkdir(parents=True, exist_ok=True)
    args.table.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    xs = [p["x_mm"] for p in kept]
    print(f"TEACH_TABLE_OK points={len(kept)} axes={args.axes} "
          f"x_range={min(xs):.1f}..{max(xs):.1f} file={args.table}")
    if len(kept) < 2:
        print("TEACH_NOTE 只有 1 点，--grasp-xy 退化为直接复用该点；"
              "至少 2 点才能沿 x 线性插值，建议 4 点覆盖实际抓取区间", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
