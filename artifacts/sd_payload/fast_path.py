"""动态拦截的快路径：直接调 C 二进制发六轴命令，绕过 Python runner 的启动开销。

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
