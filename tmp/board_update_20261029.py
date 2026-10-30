import sys
from pathlib import Path

FAST_PATH = Path("scripts/fast_path.py")
FAST_SRC = r'''"""动态拦截的快路径：直接调 C 二进制发六轴命令，绕过 Python runner 的启动开销。

为什么要单独一个模块：`g3_station_runner.py` 每次启动要 **约 1858 ms**（Python 启动 +
载计划 + 校验，板端实测 `arm_ms − cycle_ms`）。闭爪已经改走 C 单轴命令，**抬升同样不能
经过它**——否则咬合后臂要被传送带拽着对抗近 2 s，那正是抖动最明显的窗口。

放在单独文件里还有一个好处：板端更新时只需要贴一个小文件 + 两处一行改动，
不用把 45 KB 的 runner 整个贴一遍。
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import g3_station_runner as runner  # noqa: E402

# 板端六轴 C 命令。
SIX_CLI = "rtcs-pl-g2-six"
_BASE_PLAN = None


def base_plan(plan_path) -> dict:
    """缓存一份原始计划；每次用 deepcopy——apply_grasp_point 会就地改目标。"""
    global _BASE_PLAN
    if _BASE_PLAN is None:
        _BASE_PLAN = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    return _BASE_PLAN


def fast_lift(uio, plan_path, table_path, x_mm: float, y_mm: float, hold: int,
              dry_run: bool = False, log=print) -> dict:
    """发一条六轴 lift 命令并等它到位；返回 {ok, elapsed_ms, targets, output}。

    六轴命令的构造完全复用 runner 的 `apply_grasp_point` / `step_targets` /
    `build_move_six_args`，参数语义不会分叉——只是省掉了进程启动。
    """
    plan = copy.deepcopy(base_plan(plan_path))
    runner.apply_grasp_point(plan, x_mm, y_mm, Path(table_path))
    lift = next((item for item in plan["steps"] if item["name"] == "lift"), None)
    if lift is None:
        return {"ok": False, "error": "plan_has_no_lift_step", "elapsed_ms": 0}
    targets = runner.step_targets(lift, hold)
    argv = runner.build_move_six_args(uio, lift, SIX_CLI, targets,
                                      runner.DEFAULT_OBSERVE_MS, hold)
    if dry_run:
        log("DRY_RUN_FAST_LIFT " + " ".join(argv))
        return {"ok": True, "elapsed_ms": 0, "targets": targets}
    log("FAST_LIFT mono_ms=%.1f " % (time.monotonic() * 1000.0) + " ".join(argv))
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "error": str(error),
                "elapsed_ms": int((time.monotonic() - started) * 1000)}
    output = (proc.stdout or "") + (proc.stderr or "")
    return {"ok": proc.returncode == 0 and "RTCS_PL_G2_SIX_OK" in (proc.stdout or ""),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "targets": targets, "output": output}
'''

import sys
from pathlib import Path

R = Path("scripts/g3_station_runner.py")
S = Path("scripts/static_grasp_server.py")

LIFT_SKIP = '''            if resume == "place" and name == "lift":
                # 抬升也已由 server 直接发六轴命令做完：这是"取消咬合后空档"的关键一刀，
                # 否则臂要被传送带拽着对抗 1.8 s。
                print(f"G3_STEP name={name} result=SKIPPED elapsed_ms=0 reason=resume_place")
                continue
'''
ID2_BLOCK = '''        if args.grasp_id2_offset:
            # 现场指定的偏移（不是推算）：负值把夹取点抬高一点，上夹臂合拢时方块被掀起
            # 一角、与传送带的接触面变小，动态抓取时那 0.5~1 s 的摩擦对抗会明显减弱。
            for item in plan["steps"]:
                if item["name"] in GRASP_STEPS:
                    item["target_count"][1] += args.grasp_id2_offset
            print("G3_INFO grasp ID2 offset %+d" % args.grasp_id2_offset)
'''
ID2_ARG = '''    parser.add_argument("--grasp-id2-offset", type=int, default=0,
                        help="给 approach/grasp 的 ID2 目标加偏移（现场指定，不是推算）")
'''
OLD_TAIL = '''    verdict = run_cycle(x_mm, y_mm, args,
                        ("--resume", "lift", "--grip-hold", str(hold)))
'''
NEW_TAIL = '''    # 抬升也走 C 六轴快路径：闭爪读完位置后立刻抬，不再空等 runner 的 1858 ms 启动。
    lift = fast_lift(args.uio, args.plan, args.teaching_table, x_mm, y_mm, hold,
                     args.dry_run, log)
    log("FAST_LIFT_RESULT ok=%s elapsed_ms=%s targets=%s"
        % (lift["ok"], lift["elapsed_ms"], lift.get("targets")))
    if not lift["ok"]:
        for line in (lift.get("output") or lift.get("error") or "").splitlines()[-6:]:
            log("  RAW_LIFT " + line[:200])

    verdict = run_cycle(x_mm, y_mm, args,
                        ("--resume", "place", "--grip-hold", str(hold)))
'''
OLD_DISPATCH = "    verdict = run_cycle(x_mm, y_mm, args, DYNAMIC_EXTRA.get(cmd, ()))\n"
NEW_DISPATCH = '''    extra = list(DYNAMIC_EXTRA.get(cmd, ()))
    offset = packet.get("id2_offset")
    if isinstance(offset, int) and offset and cmd == "dynamic_stage":
        extra += ["--grasp-id2-offset", str(offset)]
    verdict = run_cycle(x_mm, y_mm, args, extra)
'''

PATCHES = [
    (R, '    parser.add_argument("--resume", choices=("close", "lift"), default=None,',
     '    parser.add_argument("--resume", choices=("close", "lift", "place"), default=None,'),
    (R, "    args = parser.parse_args(argv)\n", ID2_ARG + "    args = parser.parse_args(argv)\n"),
    (R, '    if args.resume == "lift" and args.grip_hold is None:',
     '    if args.resume in ("lift", "place") and args.grip_hold is None:'),
    (R, '            if resume == "lift" and name == "grasp":',
     '            if resume in ("lift", "place") and name == "grasp":'),
    (R, 'reason=resume_lift")', 'reason=resume_{resume}")'),
    (R, "            step_start = time.monotonic()\n",
     LIFT_SKIP + "            step_start = time.monotonic()\n"),
    (R, 'if resume == "lift" else None', 'if resume in ("lift", "place") else None'),
    (R, "                              args.teaching_table)\n",
     "                              args.teaching_table)\n" + ID2_BLOCK),
    (S, "from g3_station_runner import judge_gripper  # noqa: E402\n",
     "from g3_station_runner import judge_gripper  # noqa: E402\n"
     "from fast_path import fast_lift  # noqa: E402\n"),
    (S, OLD_TAIL, NEW_TAIL),
    (S, '    ok = bool(close["ok"]) and bool(verdict.get("ok"))',
     '    ok = bool(close["ok"]) and bool(lift["ok"]) and bool(verdict.get("ok"))'),
    (S, OLD_DISPATCH, NEW_DISPATCH),
]


def main():
    FAST_PATH.write_text(FAST_SRC, encoding="utf-8")
    print("WROTE %s (%d 行)" % (FAST_PATH, len(FAST_SRC.splitlines())))
    texts = {}
    for path in (R, S):
        if not path.exists():
            print("MISSING %s" % path)
            return 2
        texts[path] = path.read_text(encoding="utf-8")
    if "fast_path" in texts[S]:
        print("ALREADY_PATCHED 不需要再来一次")
        return 0
    hits = {}
    for path, old, new in PATCHES:
        current = texts[path]
        if old not in current:
            print("ANCHOR_NOT_FOUND %s\n  %r" % (path, old[:80]))
            return 3
        texts[path] = current.replace(old, new, 1)
        hits[path] = hits.get(path, 0) + 1
    for path, source in texts.items():
        try:
            compile(source, str(path), "exec")
        except SyntaxError as error:
            print("SYNTAX_ERROR %s: %s" % (path, error))
            return 4
    for path, source in texts.items():
        path.write_text(source, encoding="utf-8")
        print("PATCHED %s (%d 处)" % (path, hits.get(path, 0)))
    print("PATCH_OK 可以重启 server 了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
