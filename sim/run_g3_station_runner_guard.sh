#!/usr/bin/env bash
# G3 状态机编排层（scripts/g3_station_runner.py）的离线功能回归。
# 通过 mock 的 rtcs-pl-g2-six / rtcs-pl-g2 验证：六步顺序、故障留痕不锁死、
# 越界拒绝、抓取点覆盖、夹爪过载=夹住、接触位置接管保持、占位步真跑拒绝。
# 全程不访问 UIO、不执行运动。路径统一用相对路径（脚本已 cd 到仓库根），
# 以便同一脚本在 WSL 与 Windows Git Bash 下都能跑。
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"
mkdir -p build/sim

runner="python3 scripts/g3_station_runner.py"
B="build/sim"

# ── 生成 fixture：已确认、含夹爪动作、越界版、占位版 ──
plan="$B/g3-station-confirmed.json"
out_of_range="$B/g3-station-out-of-range.json"
placeholder="$B/g3-station-placeholder.json"
id2_over_cap="$B/g3-station-id2-over-cap.json"
teaching="$B/grasp-teaching-table.json"
python3 - "$plan" "$out_of_range" "$placeholder" "$id2_over_cap" "$teaching" <<'PY'
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
    "gripper_mapping_confirmed": True, "gripper_actuator_id": "6",
    "gripper_manual_procedure": "f", "gripper_servo_id": 6,
}
def step(name, targets, measured_at="2026-10-16T00:00", gripper=None):
    item = {"name": name, "operator_confirmed": True, "evidence": "f",
            "workspace_id": "bench-a", "path_clear_confirmed": True,
            "measured_at": measured_at,
            "target_count": targets, "speed_raw": [500]*6, "time_raw": [10]*6}
    if gripper:
        item["gripper"] = gripper
    return item
def build(t, measured_at="2026-10-16T00:00"):
    close = {"command": "close", "target_count": 2200, "expect_overload": True}
    open_ = {"command": "open", "target_count": 2500, "expect_overload": False}
    return {"schema": 1, "abi": "0x5254000E", "station": station, "steps": [
        step("standby", t, measured_at),
        step("approach", t, measured_at),
        step("grasp", t, measured_at, close),
        step("lift", t, measured_at),
        step("place", t, measured_at, open_),
        step("exit", t, measured_at),
    ]}
plan_path, oor_path, ph_path, id2_path, teaching_path = sys.argv[1:6]
base = [2000, 1000, 2500, 2400, 2000, 2500]
with open(plan_path, "w", encoding="utf-8") as h:
    json.dump(build(list(base)), h)
bad = list(base); bad[0] = 999  # ID 1 低于 safe_min 1000
with open(oor_path, "w", encoding="utf-8") as h:
    json.dump(build(bad), h)
with open(ph_path, "w", encoding="utf-8") as h:
    json.dump(build(list(base), "TODO: 占位，待示教"), h)
id2 = list(base); id2[1] = 2130  # ID 2 超过操作上限 2000（跨竖直点）
with open(id2_path, "w", encoding="utf-8") as h:
    json.dump(build(id2), h)
with open(teaching_path, "w", encoding="utf-8") as h:
    json.dump([{"x_mm": 120.5, "y_mm": -30.0, "targets": [2222, 1111, 2777]}], h)
PY

# ── mock 一：六轴总是成功，并把每次调用参数记进日志 ──
mock_ok="$B/g3-station-mock-ok.py"
cat > "$mock_ok" <<'PY'
import os, sys
log = os.environ.get("MOCK_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(sys.argv[1:]) + "\n")
print("RTCS_PL_G2_SIX_OK command=move-six elapsed_ms=1")
PY

# ── mock 二：六轴第 3 次调用（grasp 步）失败，其余成功 ──
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

# ── mock 三：夹爪单轴。闭合(2200)夹住物块=过载停在 2360；张开(2500)正常到位 ──
mock_gripper="$B/g3-station-mock-gripper.py"
cat > "$mock_gripper" <<'PY'
import os, sys
args = sys.argv[1:]
log = os.environ.get("MOCK_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(args) + "\n")
target = int(args[args.index("--target") + 1])
if target == 2200:
    print("result id=6 start=2500 target=2200 last=2360 actual_delta=-140"
          " target_error=160 in_band=0 write_sent=1 unicast_ack=1 fault=5 fault_id=6")
    print("diagnostic phase=write_or_ack engine_fault=8 servo_error_raw=0x20"
          " servo_error_bits=overload incident_position=2360 incident_position_valid=1")
    sys.stderr.write("ERR g2_fault=5 fault_id=6 write_sent=1 unicast_ack=1"
                     " servo_error_raw=0x20\n")
    sys.exit(1)
print("RTCS_PL_G2_OK id=6 target=2500 position_raw=2490 final_error=10"
      " actual_delta=UNAVAILABLE samples=12 elapsed_ms=700 timing=WITHIN_2S")
PY

# ── 1) 顺序与夹爪拆分：六步 6 次 move-six + 夹爪 2 次单轴 ──
: > "$B/g3-mock-order.log"
MOCK_LOG="$B/g3-mock-order.log" \
  $runner "$plan" --once --six-cli "python3 $mock_ok" \
  --single-cli "python3 $mock_gripper" >"$B/g3-order.out" 2>&1
grep -q '^G3_CYCLE end=1 success=1$' "$B/g3-order.out"
grep -q '^G3_RUN_SUMMARY cycles=1 failures=0 aborted=0$' "$B/g3-order.out"
# 夹爪保持态（lift/place）走逐轴，不碰 ID6；其余四步走 move-six
[[ $(grep -c ' move-six ' "$B/g3-mock-order.log") -eq 4 ]]
[[ $(grep -c ' move --id 6 ' "$B/g3-mock-order.log") -eq 2 ]]
[[ $(grep -cE ' move --id [1-5] ' "$B/g3-mock-order.log") -eq 10 ]]
[[ $(grep -o -- '--axis ' "$B/g3-mock-order.log" | wc -l) -eq 24 ]]
grep -q -- '--axis 1:2000:500:10' "$B/g3-mock-order.log"
grep -q -- '--observe-ms 8000' "$B/g3-mock-order.log"
# 夹爪闭合是过载工况：判定为 CONTACT 而不是失败，接触位置 2360 留痕
grep -q '^G3_STEP name=grasp.gripper result=CONTACT position=2360$' "$B/g3-order.out"
grep -q '^G3_STEP name=place.gripper result=OK position=2490$' "$B/g3-order.out"
# grasp 步六轴到位时夹爪仍张开（2500），闭合目标不并进六轴命令
grep -q -- '--axis 6:2500:500:10' "$B/g3-mock-order.log"

# ── 2) 夹爪保持态逐轴搬运：lift/place 只动 ID1-5，ID6 不参与 ──
grep -q '^G3_STEP name=lift result=OK gripper_hold=2360$' "$B/g3-order.out"
grep -q '^G3_STEP name=place result=OK gripper_hold=2360$' "$B/g3-order.out"
# 全程不应出现 move-six 带 ID6=2360 的保持写法（已改为逐轴）
if grep -q -- '--axis 6:2360' "$B/g3-mock-order.log"; then
  echo 'held transit still routes ID6 through move-six' >&2; exit 1
fi

# ── 3) 故障留痕不锁死：grasp 失败 -> exit 安全回位 -> 本轮失败；--loop 2 继续第二轮 ──
: > "$B/g3-mock-fail.log"; : > "$B/g3-mock-fail.count"
MOCK_LOG="$B/g3-mock-fail.log" MOCK_COUNT="$B/g3-mock-fail.count" \
  $runner "$plan" --loop 2 --six-cli "python3 $mock_grasp_fail" \
  --single-cli "python3 $mock_gripper" >"$B/g3-fail.out" 2>&1 || true
grep -q '^G3_STEP name=grasp result=FAIL fault=ERR g2_six_fault=5' "$B/g3-fail.out"
grep -q '^G3_STEP name=exit result=OK recovery=true$' "$B/g3-fail.out"
grep -q '^G3_CYCLE end=1 success=0$' "$B/g3-fail.out"
grep -q '^G3_CYCLE start=2/2$' "$B/g3-fail.out"
# 第一轮 grasp 失败、第二轮完整跑通：证明故障不锁死、下一轮能正常继续
grep -q '^G3_CYCLE end=2 success=1$' "$B/g3-fail.out"
grep -q '^G3_RUN_SUMMARY cycles=2 failures=1 aborted=0$' "$B/g3-fail.out"

# ── 4) 越界计划必须被门禁拒绝，且不执行任何运动 ──
if $runner "$out_of_range" --once --six-cli "python3 $mock_ok" \
    --single-cli "python3 $mock_gripper" >"$B/g3-oor.out" 2>&1; then
  echo 'Out-of-range plan was accepted' >&2; exit 1
fi
grep -q '^G3_PLAN_REJECTED ' "$B/g3-oor.out"

# ── 4b) ID2 超过操作建议值 2000：只告警、不拦截（可达性以现场实测为准） ──
if ! $runner "$id2_over_cap" --once --dry-run --six-cli "python3 $mock_ok" \
    --single-cli "python3 $mock_gripper" >"$B/g3-id2.out" 2>&1; then
  echo 'ID2-over-hint plan was blocked; expected a warning only' >&2; exit 1
fi
grep -q 'G3_WARN grasp: ID 2 target 2130 above operating hint 2000' "$B/g3-id2.out"

# ── 5) 占位步：dry-run 允许打印，真跑必须拒绝（approach/lift 没示教就不许动） ──
$runner "$placeholder" --once --dry-run --six-cli "python3 $mock_ok" \
  --single-cli "python3 $mock_gripper" >"$B/g3-ph-dry.out" 2>&1
grep -q '^G3_CYCLE end=1 success=1$' "$B/g3-ph-dry.out"
grep -q 'DRY_RUN .*move-six' "$B/g3-ph-dry.out"
if $runner "$placeholder" --once --six-cli "python3 $mock_ok" \
    --single-cli "python3 $mock_gripper" >"$B/g3-ph-run.out" 2>&1; then
  echo 'Placeholder plan was accepted for real execution' >&2; exit 1
fi
grep -q 'placeholder pose' "$B/g3-ph-run.out"

# ── 6) 抓取点覆盖：--grasp-xy 让 approach 步的 ID1-3 目标换成映射值 ──
$runner "$plan" --once --dry-run --grasp-xy 120.5,-30.0 \
  --teaching-table "$teaching" --six-cli "python3 $mock_ok" \
  --single-cli "python3 $mock_gripper" >"$B/g3-grasp.out" 2>&1
grep -q -- '--axis 1:2222:500:10' "$B/g3-grasp.out"
grep -q -- '--axis 2:1111:500:10' "$B/g3-grasp.out"
grep -q -- '--axis 3:2777:500:10' "$B/g3-grasp.out"
grep -q -- '--axis 1:2000:500:10' "$B/g3-grasp.out"

# ── 7) 缺 --teaching-table 时 --grasp-xy 必须报参数错误 ──
if $runner "$plan" --once --grasp-xy 0,0 --six-cli "python3 $mock_ok" \
    --single-cli "python3 $mock_gripper" >"$B/g3-grasp-no-table.out" 2>&1; then
  echo '--grasp-xy without --teaching-table was accepted' >&2; exit 1
fi

echo RTCS_G3_STATION_RUNNER_GUARD_PASS
