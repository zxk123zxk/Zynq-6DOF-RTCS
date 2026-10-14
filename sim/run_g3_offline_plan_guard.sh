#!/usr/bin/env bash
# G3 离线任务表校验的功能回归。
# scripts/g3_offline_plan.py 只做离线 JSON/TOML 检查并打印一条待人工审阅的命令，
# 不访问 UIO、不执行运动；本测试逐条钉住它的门禁，尤其是 "ID 5 未放行即拒绝"。
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"
build_dir="$repo_root/build/sim"
mkdir -p "$build_dir"

plan="$build_dir/g3-plan-confirmed.json"
no_clearance="$build_dir/g3-plan-no-id5-clearance.json"
out_of_range="$build_dir/g3-plan-id5-out-of-range.json"
no_preflight="$build_dir/g3-plan-no-preflight.json"

python3 - "$plan" "$no_clearance" "$out_of_range" "$no_preflight" <<'PY'
import json, sys

ORDER = ("standby", "approach", "grasp", "lift", "place", "exit")

station = {
    "operator_confirmed": True,
    "evidence": "fixture",
    "workspace_id": "bench-a",
    "measured_boundary": "fixture boundary",
    "preflight": {
        "probe_log": "fixture probe", "limits_log": "fixture limits",
        "diagnose_log": "fixture diagnose",
        "torque_status_id5_log": "fixture torque status",
        "joint_directions_log": "fixture joint directions",
        "payload_obstacles_log": "fixture payload and obstacles",
        "software_stop_latency_log": "fixture software stop",
        "independent_power_cut_estop_log": "fixture independent estop",
        "operator_confirmed": True,
    },
    "id5_fault_cleared_by_operator": True,
    "id5_clearance_evidence": "fixture clearance",
    "gripper_mapping_confirmed": True,
    "gripper_actuator_id": "separate",
    "gripper_manual_procedure": "fixture procedure",
    "gripper_servo_id": None,
}


def step(name, id5_target):
    return {
        "name": name,
        "operator_confirmed": True,
        "evidence": "fixture",
        "workspace_id": "bench-a",
        "path_clear_confirmed": True,
        "measured_at": "2026-10-10T00:00",
        "target_count": [2000, 1000, 2500, 2400, id5_target, 2500],
        "speed_raw": [500, 500, 500, 500, 500, 500],
        "time_raw": [10, 10, 10, 10, 10, 10],
    }


def build(id5_target, record):
    return {"schema": 1, "abi": "0x5254000E", "station": record,
            "steps": [step(name, id5_target) for name in ORDER]}


plan_path, no_clearance_path, out_of_range_path, no_preflight_path = sys.argv[1:5]
with open(plan_path, "w", encoding="utf-8") as handle:
    json.dump(build(2000, station), handle)

without = dict(station)
del without["id5_fault_cleared_by_operator"]
with open(no_clearance_path, "w", encoding="utf-8") as handle:
    json.dump(build(2000, without), handle)

# 4001 超出 config 里 ID 5 的实测上界 4000（该行本身是待重测的占位值）。
with open(out_of_range_path, "w", encoding="utf-8") as handle:
    json.dump(build(4001, station), handle)

without_preflight = dict(station)
del without_preflight["preflight"]
with open(no_preflight_path, "w", encoding="utf-8") as handle:
    json.dump(build(2000, without_preflight), handle)
PY

run() { python3 scripts/g3_offline_plan.py "$@"; }

# 1) 空白模板必须被拒，且原因要说清是缺操作者确认。
if run config/g3_station_plan.template.json >"$build_dir/g3-template.out" 2>&1; then
  echo 'Empty station template was accepted' >&2
  exit 1
fi
grep -q '^G3_PLAN_REJECTED ' "$build_dir/g3-template.out"
grep -q 'operator confirmation missing' "$build_dir/g3-template.out"

# 2) ID 5 未经操作者放行必须被拒 —— 这是 G3 门禁的本体。
if run "$no_clearance" --step standby >"$build_dir/g3-no-id5.out" 2>&1; then
  echo 'Plan without ID 5 operator clearance was accepted' >&2
  exit 1
fi
grep -q 'ID 5 fault investigation and operator clearance required' "$build_dir/g3-no-id5.out"

# 3) 即使 ID 5 已放行，缺只读/急停证据仍不能生成命令。
if run "$no_preflight" --step standby >"$build_dir/g3-no-preflight.out" 2>&1; then
  echo 'Plan without preflight evidence was accepted' >&2
  exit 1
fi
grep -q 'read-only, workspace and stop/estop preflight evidence required' \
  "$build_dir/g3-no-preflight.out"

# 4) 目标越界必须被拒。这条同时证明 safe_min/safe_max 真的被读到了，
#    而不是解析失败后放行一切（WSL 的 Python 3.10 走的是回退解析路径）。
if run "$out_of_range" --step standby >"$build_dir/g3-out-of-range.out" 2>&1; then
  echo 'Out-of-range ID 5 target was accepted' >&2
  exit 1
fi
grep -q 'standby: ID 5 outside measured PL range' "$build_dir/g3-out-of-range.out"

# 5) 填实且已放行的任务表在 standby 步应通过，且绝不执行运动。
run "$plan" --step standby >"$build_dir/g3-standby.out" 2>&1
grep -q '^G3_PLAN_OFFLINE_VALID through=standby motion_executed=0$' "$build_dir/g3-standby.out"
grep -q '^MANUAL_REVIEW_ONLY sudo rtcs-pl-g2-six --uio /dev/uio0 move-six' \
  "$build_dir/g3-standby.out"
[[ $(grep -o -- '--axis ' "$build_dir/g3-standby.out" | wc -l) -eq 6 ]]
grep -q -- '--execute' "$build_dir/g3-standby.out"

# 6) standby 之后缺观测记录必须被拒。
if run "$plan" --step approach >"$build_dir/g3-approach-no-log.out" 2>&1; then
  echo 'Step after standby without an observation log was accepted' >&2
  exit 1
fi
grep -q 'log required after standby' "$build_dir/g3-approach-no-log.out"

# 7) 它只能打印待人工审阅的命令，不得声称执行过运动。
if grep -q 'motion_executed=1' "$build_dir/g3-standby.out"; then
  echo 'G3 offline plan claimed to execute motion' >&2
  exit 1
fi
[[ $(grep -c '^MANUAL_REVIEW_ONLY ' "$build_dir/g3-standby.out") -eq 1 ]]

echo RTCS_G3_OFFLINE_PLAN_GUARD_PASS
