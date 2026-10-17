#!/usr/bin/env bash
# G3 状态机编排层（scripts/g3_station_runner.py）的离线功能回归。
# 通过 mock 的 rtcs-pl-g2-six 验证：六步顺序、故障留痕不锁死、越界拒绝、抓取点覆盖。
# 全程不访问 UIO、不执行运动。路径统一用相对路径（脚本已 cd 到仓库根），
# 以便同一脚本在 WSL 与 Windows Git Bash 下都能跑。
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"
mkdir -p build/sim

runner="python3 scripts/g3_station_runner.py"
B="build/sim"

# ── 生成一个"已确认且越界不成立"的工位计划 fixture ──
plan="$B/g3-station-confirmed.json"
out_of_range="$B/g3-station-out-of-range.json"
teaching="$B/grasp-teaching-table.json"
python3 - "$plan" "$out_of_range" "$teaching" <<'PY'
import json, sys
ORDER = ("standby", "approach", "grasp", "lift", "place", "exit")
station = {
    "operator_confirmed": True, "evidence": "fixture", "workspace_id": "bench-a",
    "measured_boundary": "fixture boundary",
    "preflight": {
        "probe_log": "f", "limits_log": "f", "diagnose_log": "f",
        "torque_status_id5_log": "f", "joint_directions_log": "f",
        "payload_obstacles_log": "f", "software_stop_latency_log": "f",
        "independent_power_cut_estop_log": "f", "operator_confirmed": True,
    },
    "id5_fault_cleared_by_operator": True, "id5_clearance_evidence": "f",
    "gripper_mapping_confirmed": True, "gripper_actuator_id": "separate",
    "gripper_manual_procedure": "f", "gripper_servo_id": None,
}
def step(name, targets):
    return {"name": name, "operator_confirmed": True, "evidence": "f",
            "workspace_id": "bench-a", "path_clear_confirmed": True,
            "measured_at": "2026-10-16T00:00",
            "target_count": targets, "speed_raw": [500]*6, "time_raw": [10]*6}
plan_path, oor_path, teaching_path = sys.argv[1:4]
def build(t):
    return {"schema": 1, "abi": "0x5254000E", "station": station,
            "steps": [step(n, t) for n in ORDER]}
base = [2000, 1000, 2500, 2400, 2000, 2500]
with open(plan_path, "w", encoding="utf-8") as h:
    json.dump(build(list(base)), h)
bad = list(base); bad[0] = 999  # ID 1 低于 safe_min 1000
with open(oor_path, "w", encoding="utf-8") as h:
    json.dump(build(bad), h)
with open(teaching_path, "w", encoding="utf-8") as h:
    json.dump([{"x_mm": 120.5, "y_mm": -30.0, "targets": [2222, 1111, 2777]}], h)
PY

# ── mock 一：总是成功，并把每次调用参数记进日志 ──
mock_ok="$B/g3-station-mock-ok.py"
cat > "$mock_ok" <<'PY'
import os, sys
log = os.environ.get("MOCK_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(sys.argv[1:]) + "\n")
print("RTCS_PL_G2_SIX_OK command=move-six elapsed_ms=1")
PY

# ── mock 二：第 3 次调用（grasp 步）失败，其余成功 ──
mock_grasp_fail="$B/g3-station-mock-grasp-fail.py"
cat > "$mock_grasp_fail" <<'PY'
import os, sys
log = os.environ.get("MOCK_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(sys.argv[1:]) + "\n")
count = 0
count_file = os.environ.get("MOCK_COUNT")
if count_file:
    try:
        count = int(open(count_file, encoding="utf-8").read().strip())
    except Exception:
        count = 0
count += 1
if count_file:
    with open(count_file, "w", encoding="utf-8") as f:
        f.write(str(count))
if count == 3:
    sys.stderr.write("ERR g2_six_fault=5 fault_id=3 write_sent=1 reason=read_or_protocol_failure\n")
    sys.exit(1)
print("RTCS_PL_G2_SIX_OK command=move-six elapsed_ms=1")
PY

# ── 1) 顺序正确：--once 跑一遍，六步按序且全 OK ──
: > "$B/g3-mock-order.log"
MOCK_LOG="$B/g3-mock-order.log" \
  $runner "$plan" --once --six-cli "python3 $mock_ok" >"$B/g3-order.out" 2>&1
grep -q '^G3_CYCLE end=1 success=1$' "$B/g3-order.out"
grep -q '^G3_RUN_SUMMARY cycles=1 failures=0 aborted=0$' "$B/g3-order.out"
[[ $(grep -c ' move-six ' "$B/g3-mock-order.log") -eq 6 ]]
[[ $(grep -o -- '--axis ' "$B/g3-mock-order.log" | wc -l) -eq 36 ]]
grep -q -- '--axis 1:2000:500:10' "$B/g3-mock-order.log"

# ── 2) 故障留痕不锁死：grasp 失败 -> exit 安全回位 -> 本轮失败；--loop 2 继续第二轮 ──
: > "$B/g3-mock-fail.log"; : > "$B/g3-mock-fail.count"
MOCK_LOG="$B/g3-mock-fail.log" MOCK_COUNT="$B/g3-mock-fail.count" \
  $runner "$plan" --loop 2 --six-cli "python3 $mock_grasp_fail" >"$B/g3-fail.out" 2>&1 || true
grep -q '^G3_STEP name=grasp result=FAIL fault=ERR g2_six_fault=5' "$B/g3-fail.out"
grep -q '^G3_STEP name=exit result=OK recovery=true$' "$B/g3-fail.out"
grep -q '^G3_CYCLE end=1 success=0$' "$B/g3-fail.out"
grep -q '^G3_CYCLE start=2/2$' "$B/g3-fail.out"
# 第一轮 grasp 失败、第二轮完整跑通：证明故障不锁死、下一轮能正常继续
grep -q '^G3_CYCLE end=2 success=1$' "$B/g3-fail.out"
grep -q '^G3_RUN_SUMMARY cycles=2 failures=1 aborted=0$' "$B/g3-fail.out"

# ── 3) 越界计划必须被门禁拒绝，且不执行任何运动 ──
if $runner "$out_of_range" --once --six-cli "python3 $mock_ok" >"$B/g3-oor.out" 2>&1; then
  echo 'Out-of-range plan was accepted' >&2; exit 1
fi
grep -q '^G3_PLAN_REJECTED ' "$B/g3-oor.out"

# ── 4) 抓取点覆盖：--grasp-xy 让 approach 步的 ID1-3 目标换成映射值 ──
$runner "$plan" --once --dry-run --grasp-xy 120.5,-30.0 \
  --teaching-table "$teaching" --six-cli "python3 $mock_ok" >"$B/g3-grasp.out" 2>&1
grep -q -- '--axis 1:2222:500:10' "$B/g3-grasp.out"
grep -q -- '--axis 2:1111:500:10' "$B/g3-grasp.out"
grep -q -- '--axis 3:2777:500:10' "$B/g3-grasp.out"
grep -q -- '--axis 1:2000:500:10' "$B/g3-grasp.out"

# ── 5) 缺 --teaching-table 时 --grasp-xy 必须报参数错误 ──
if $runner "$plan" --once --grasp-xy 0,0 --six-cli "python3 $mock_ok" \
    >"$B/g3-grasp-no-table.out" 2>&1; then
  echo '--grasp-xy without --teaching-table was accepted' >&2; exit 1
fi

echo RTCS_G3_STATION_RUNNER_GUARD_PASS
