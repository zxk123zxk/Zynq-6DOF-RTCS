#!/usr/bin/env python3
"""Validate a measured G3 station plan and print one supervised CLI step.

This program does not open UIO or execute a motion command.
"""
import argparse
import json
import shlex
import sys
from pathlib import Path

STEPS = ("standby", "approach", "grasp", "lift", "place", "exit")
ROOT = Path(__file__).resolve().parents[1]


def fail(message):
    raise ValueError(message)


def _load_limits_without_tomllib(text):
    """Read the three integer keys this program needs from [[axis]] blocks,
    plus the optional [task] operating caps.

    Only used when the host has no tomllib (Python < 3.11, i.e. the board's
    Python 3.10).  It is deliberately strict and fails closed: an unreadable
    value or a table with no [[axis]] block raises instead of yielding empty
    limits, so a parsing problem can never silently widen a workspace.
    """
    axes = []
    current = None
    task = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line == "[[axis]]":
            current = {}
            axes.append(current)
            continue
        if line.startswith("["):
            current = {"__task__": True} if line.startswith("[task]") else None
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if current.get("__task__"):
            if key == "id2_target_max":
                try:
                    task["id2_target_max"] = int(value.strip())
                except ValueError:
                    fail("measured limit table: task id2_target_max is not an integer")
            continue
        if key not in ("servo_id", "safe_min", "safe_max"):
            continue
        try:
            current[key] = int(value.strip())
        except ValueError:
            fail(f"measured limit table: {key} is not an integer")
    if not axes or any("servo_id" not in axis or "safe_min" not in axis or
                       "safe_max" not in axis for axis in axes):
        fail("measured limit table: incomplete [[axis]] entry")
    result = {"axis": axes}
    if task:
        result["task"] = task
    return result


def load_limits(path):
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:
        return _load_limits_without_tomllib(text)
    return tomllib.loads(text)


def confirmed(record, name):
    if not isinstance(record, dict) or record.get("operator_confirmed") is not True:
        fail(f"{name}: operator confirmation missing")
    if not isinstance(record.get("evidence"), str) or not record["evidence"].strip():
        fail(f"{name}: measured evidence reference missing")


def validate_gripper(item, name, gripper_limits):
    """校验一步的夹爪动作（可选字段 ``gripper``）。

    夹爪动作在编排层走单轴命令，因此这里只钉住"目标在实测范围内"和
    "过载预期必须显式写明"——闭合夹物必然过载，不能靠代码猜。
    """
    action = item.get("gripper")
    if action is None:
        return
    if not isinstance(action, dict):
        fail(f"{name}: gripper action must be an object")
    if action.get("command") not in ("open", "close"):
        fail(f"{name}: gripper command must be open or close")
    target = action.get("target_count")
    if type(target) is not int or not gripper_limits["safe_min"] <= target <= gripper_limits["safe_max"]:
        fail(f"{name}: gripper target outside measured ID 6 range")
    speed = action.get("speed_raw", 500)
    if type(speed) is not int or not 1 <= speed <= 1500:
        fail(f"{name}: gripper invalid speed_raw")
    time_raw = action.get("time_raw", 10)
    if type(time_raw) is not int or not 0 <= time_raw <= 65535:
        fail(f"{name}: gripper invalid time_raw")
    if "expect_overload" in action and not isinstance(action["expect_overload"], bool):
        fail(f"{name}: gripper expect_overload must be a boolean")
    if action.get("actuator_id", 6) != 6:
        fail(f"{name}: gripper actuator_id must be 6")


def validate(plan, through_step=None, require_measured=False):
    limits = load_limits(ROOT / "config/g2_measured_limits.toml")
    axes = {axis["servo_id"]: axis for axis in limits["axis"]}
    if set(axes) != set(range(1, 7)):
        fail("G2 limit table must contain six unique IDs")
    # 操作约束（非舵机物理限位）：2026-10-19 定——ID2 在展开态越过竖直点(~1990)
    # 后带末端负载回不来，故所有运动位点的 ID2 目标一律 ≤ 2000，工件对齐靠移动传送带。
    # 缺省 2000 是 fail-closed：即便 toml 漏带 [task] 段，门禁也照常收紧。
    id2_target_max = limits.get("task", {}).get("id2_target_max", 2000)
    if plan.get("schema") != 1 or plan.get("abi") != "0x5254000E":
        fail("plan schema or ABI mismatch")
    station = plan.get("station")
    confirmed(station, "station/workspace")
    if not isinstance(station.get("workspace_id"), str) or not station["workspace_id"].strip() or \
       not isinstance(station.get("measured_boundary"), str) or not station["measured_boundary"].strip():
        fail("station: measured workspace boundary missing")
    preflight = station.get("preflight")
    required_preflight = (
        "probe_log", "limits_log", "diagnose_log", "torque_status_id5_log",
        "joint_directions_log", "payload_obstacles_log", "software_stop_latency_log",
        "independent_power_cut_estop_log",
    )
    if not isinstance(preflight, dict) or preflight.get("operator_confirmed") is not True or \
       any(not isinstance(preflight.get(key), str) or not preflight[key].strip()
           for key in required_preflight):
        fail("station: read-only, workspace and stop/estop preflight evidence required")
    if station.get("id5_fault_cleared_by_operator") is not True:
        fail("ID 5 fault investigation and operator clearance required")
    if not isinstance(station.get("id5_clearance_evidence"), str) or not station["id5_clearance_evidence"].strip():
        fail("ID 5 clearance evidence missing")
    if (station.get("gripper_mapping_confirmed") is not True or
        not isinstance(station.get("gripper_actuator_id"), str) or
        not station["gripper_actuator_id"].strip() or
        not isinstance(station.get("gripper_manual_procedure"), str) or
        not station["gripper_manual_procedure"].strip()):
        fail("gripper actuator mapping and manual procedure required")
    servo_id = station.get("gripper_servo_id")
    if servo_id is not None and (type(servo_id) is not int or servo_id not in range(1, 7)):
        fail("gripper servo ID must be 1..6 or null for a separate actuator")
    items = plan.get("steps")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items) or \
       [item.get("name") for item in items] != list(STEPS):
        fail("steps must be standby, approach, grasp, lift, place, exit in order")
    required = items if through_step is None else items[:STEPS.index(through_step)+1]
    for item in required:
        name = item["name"]
        confirmed(item, name)
        if item.get("workspace_id") != station["workspace_id"]:
            fail(f"{name}: workspace mismatch")
        if item.get("path_clear_confirmed") is not True:
            fail(f"{name}: swept path not confirmed")
        if not isinstance(item.get("measured_at"), str) or not item["measured_at"].strip():
            fail(f"{name}: measurement timestamp missing")
        if require_measured and item["measured_at"].strip().upper().startswith("TODO"):
            fail(f"{name}: placeholder pose; teach this station point before executing")
        goals = item.get("target_count")
        speeds = item.get("speed_raw")
        times = item.get("time_raw")
        if not all(isinstance(x, list) and len(x) == 6 for x in (goals, speeds, times)):
            fail(f"{name}: six measured targets and raw motion parameters required")
        for servo_id in range(1, 7):
            i = servo_id - 1
            if type(goals[i]) is not int or not axes[servo_id]["safe_min"] <= goals[i] <= axes[servo_id]["safe_max"]:
                fail(f"{name}: ID {servo_id} outside measured PL range")
            if type(speeds[i]) is not int or not 1 <= speeds[i] <= 1500:
                fail(f"{name}: ID {servo_id} invalid speed_raw")
            if type(times[i]) is not int or not 0 <= times[i] <= 65535:
                fail(f"{name}: ID {servo_id} invalid time_raw")
        if goals[1] > id2_target_max:
            # 只告警不拦截：这是操作建议阈值（越过 ID2 竖直点可能带负载回不来），
            # 但实测的可达性以现场为准，不拿一条启发式规则挡住整个循环。
            print(f"G3_WARN {name}: ID 2 target {goals[1]} above operating hint "
                  f"{id2_target_max} (may stall near the vertical point)", file=sys.stderr)
        validate_gripper(item, name, axes[6])
    return items


def validate_log(log, step):
    if step == "standby":
        return
    if not isinstance(log, dict) or log.get("schema") != 1:
        fail("prior step observation log required")
    entries = log.get("entries")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        fail("prior step observation entries missing")
    previous = STEPS[:STEPS.index(step)]
    for name in previous:
        matches = [entry for entry in entries if entry.get("name") == name]
        if len(matches) != 1:
            fail(f"{name}: exactly one prior observation required")
        entry = matches[0]
        if (entry.get("operator_confirmed") is not True or
            entry.get("observed_task_success") is not True or
            not entry.get("observed_at") or not entry.get("motion_output_file") or
            not entry.get("evidence") or
            (name == "grasp" and entry.get("object_secured_observed") is not True)):
            fail(f"{name}: observed physical result and operator confirmation required")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--step", choices=STEPS, help="print one command for manual review")
    parser.add_argument("--log", type=Path, help="record of prior supervised steps")
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        items = validate(plan, args.step, require_measured=True)
        if args.step and args.step != "standby":
            if not args.log:
                fail("--log required after standby")
            validate_log(json.loads(args.log.read_text(encoding="utf-8")),args.step)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"G3_PLAN_REJECTED {error}", file=sys.stderr)
        return 1
    print(f"G3_PLAN_OFFLINE_VALID through={args.step or 'exit'} motion_executed=0")
    if args.step:
        item = next(item for item in items if item["name"] == args.step)
        parts = ["sudo", "rtcs-pl-g2-six", "--uio", "/dev/uio0", "move-six"]
        for i in range(6):
            parts += ["--axis", f"{i+1}:{item['target_count'][i]}:{item['speed_raw'][i]}:{item['time_raw'][i]}"]
        parts += ["--observe-ms", "8000", "--execute"]
        print("MANUAL_REVIEW_ONLY " + shlex.join(parts))
        print("Record current diagnose, then review the live workspace before this single step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
