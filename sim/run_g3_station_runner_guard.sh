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

# ── 0) 板端 Python 兼容：3.12 才允许的语法（f-string 嵌套同类引号）在板上是 SyntaxError ──
# 本地 py_compile 用 3.13 看不出来；2026-10-29 因此白跑一趟上板（runner 231 ms 退出、
# 一行 G3_ 输出都没有，看着像"什么都没发生"）。
python3 scripts/check_py_compat.py scripts/*.py >"$B/py-compat.out" 2>&1 || {
  cat "$B/py-compat.out" >&2
  exit 1
}

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
        step("retreat", t, measured_at),
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

# ── 1) 顺序与夹爪拆分：七步 7 次 move-six + 夹爪 2 次单轴 ──
: > "$B/g3-mock-order.log"
MOCK_LOG="$B/g3-mock-order.log" \
  $runner "$plan" --once --six-cli "python3 $mock_ok" \
  --single-cli "python3 $mock_gripper" >"$B/g3-order.out" 2>&1
grep -q '^G3_CYCLE end=1 success=1' "$B/g3-order.out"
grep -q '^G3_RUN_SUMMARY cycles=1 failures=0 aborted=0$' "$B/g3-order.out"
# 全程六轴（夹爪过载由 PL 的 --ignore-error 6 屏蔽，不再降级逐轴）
[[ $(grep -c ' move-six ' "$B/g3-mock-order.log") -eq 7 ]]
[[ $(grep -c ' move --id 6 ' "$B/g3-mock-order.log") -eq 2 ]]
[[ $(grep -o -- '--axis ' "$B/g3-mock-order.log" | wc -l) -eq 42 ]]
grep -q -- '--axis 1:2000:500:10' "$B/g3-mock-order.log"
grep -q -- '--observe-ms 8000' "$B/g3-mock-order.log"
# 每条六轴命令都屏蔽夹爪错误；除 grasp 外都放行 ID3 的到位判定
[[ $(grep -c -- '--ignore-error 6' "$B/g3-mock-order.log") -eq 7 ]]
[[ $(grep -c -- '--ignore-arrival 3' "$B/g3-mock-order.log") -eq 6 ]]
# 夹持期间（lift/place）还必须放行 ID6 的到位判定，否则它会因过载漂移拖满观察期
[[ $(grep -c -- '--ignore-arrival 6' "$B/g3-mock-order.log") -eq 2 ]]
# 夹爪闭合是过载工况：判定为 CONTACT 而不是失败，接触位置 2360 留痕
grep -q '^G3_STEP name=grasp.gripper result=CONTACT elapsed_ms=[0-9]* position=2360' "$B/g3-order.out"
grep -q '^G3_STEP name=place.gripper result=OK elapsed_ms=[0-9]* position=2490' "$B/g3-order.out"
# grasp 步六轴到位时夹爪仍张开（2500），闭合目标不并进六轴命令
grep -q -- '--axis 6:2500:500:10' "$B/g3-mock-order.log"

# ── 2) 夹持段仍走六轴，ID6 用接触位置保持 ──
grep -q '^G3_STEP name=lift result=OK elapsed_ms=[0-9]* gripper_hold=2360' "$B/g3-order.out"
grep -q '^G3_STEP name=place result=OK elapsed_ms=[0-9]* gripper_hold=2360' "$B/g3-order.out"
grep -q -- '--axis 6:2360:500:10' "$B/g3-mock-order.log"

# ── 3) 故障留痕不锁死：grasp 失败 -> exit 安全回位 -> 本轮失败；--loop 2 继续第二轮 ──
: > "$B/g3-mock-fail.log"; : > "$B/g3-mock-fail.count"
MOCK_LOG="$B/g3-mock-fail.log" MOCK_COUNT="$B/g3-mock-fail.count" \
  $runner "$plan" --loop 2 --six-cli "python3 $mock_grasp_fail" \
  --single-cli "python3 $mock_gripper" >"$B/g3-fail.out" 2>&1 || true
grep -q '^G3_STEP name=grasp result=FAIL fault=ERR g2_six_fault=5' "$B/g3-fail.out"
grep -q '^G3_STEP name=exit result=OK recovery=true$' "$B/g3-fail.out"
grep -q '^G3_CYCLE end=1 success=0' "$B/g3-fail.out"
grep -q '^G3_CYCLE start=2/2$' "$B/g3-fail.out"
# 第一轮 grasp 失败、第二轮完整跑通：证明故障不锁死、下一轮能正常继续
grep -q '^G3_CYCLE end=2 success=1' "$B/g3-fail.out"
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
grep -q 'G3_WARN grasp: ID 2 target 2130 above operating hint 2020' "$B/g3-id2.out"

# ── 5) 占位步：dry-run 允许打印，真跑必须拒绝（approach/lift 没示教就不许动） ──
$runner "$placeholder" --once --dry-run --six-cli "python3 $mock_ok" \
  --single-cli "python3 $mock_gripper" >"$B/g3-ph-dry.out" 2>&1
grep -q '^G3_CYCLE end=1 success=1' "$B/g3-ph-dry.out"
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

# ── 8) --stop-after grasp：走到拦截位就收尾，夹爪保持张开、绝不闭爪 ──
# 这是动态拦截"提前就位"的入口：臂停在抓取位等外部触发，闭爪必须留给后面单独下发。
: > "$B/g3-mock-stop.log"
MOCK_LOG="$B/g3-mock-stop.log" \
  $runner "$plan" --once --grasp-xy 120.5,-30.0 --teaching-table "$teaching" \
  --stop-after grasp --six-cli "python3 $mock_ok" \
  --single-cli "python3 $mock_gripper" >"$B/g3-stop.out" 2>&1
grep -q '^G5_READY_AT step=grasp' "$B/g3-stop.out"
grep -q '^G3_CYCLE end=1 success=1 grip=open stopped_after=grasp' "$B/g3-stop.out"
# --grasp-xy 会跳过 standby，所以只走 approach + grasp 两条六轴命令
[[ $(grep -c ' move-six ' "$B/g3-mock-stop.log") -eq 2 ]]
# 夹爪一次都没动过（这一刀的全部意义所在）
[[ $(grep -c ' move --id 6 ' "$B/g3-mock-stop.log") -eq 0 ]]
# 后面的 lift/place/retreat/exit 一个都不许出现
for later in lift place retreat exit; do
  if grep -q "^G3_STEP name=$later " "$B/g3-stop.out"; then
    echo "stop-after grasp still executed $later" >&2; exit 1
  fi
done

# ── 9) --resume close：臂已在拦截位，只闭爪 + 搬运 ──
# 动态拦截的后半段：movement 一步都不许有，**第一条运动命令必须是夹爪闭合**。
: > "$B/g3-mock-resume.log"
MOCK_LOG="$B/g3-mock-resume.log" \
  $runner "$plan" --once --grasp-xy 120.5,-30.0 --teaching-table "$teaching" \
  --resume close --six-cli "python3 $mock_ok" \
  --single-cli "python3 $mock_gripper" >"$B/g3-resume.out" 2>&1
grep -q '^G3_STEP name=approach result=SKIPPED elapsed_ms=0 reason=resume_close' "$B/g3-resume.out"
grep -q '^G3_STEP name=grasp result=SKIPPED elapsed_ms=0 reason=resume_close' "$B/g3-resume.out"
grep -q '^G3_STEP name=grasp.gripper result=CONTACT' "$B/g3-resume.out"
grep -q '^G3_STEP name=lift result=OK*' "$B/g3-resume.out"
grep -q 'gripper_hold=2360' "$B/g3-resume.out"
grep -q '^G3_CYCLE end=1 success=1 grip=contact' "$B/g3-resume.out"
# 闭爪必须是第一条运动命令（否则"提前量"又被舵机吃回去了）
head -1 "$B/g3-mock-resume.log" | grep -q ' move --id 6 '
# 闭爪之后才轮到 lift/place/retreat/exit 四条六轴命令（retreat 也是整步 move-six）
[[ $(grep -c ' move-six ' "$B/g3-mock-resume.log") -eq 4 ]]

# ── 10) --resume lift：闭爪已由 server 的 C 快路径做完，runner 从 lift 起 ──
# 这一刀的意义是把 880 ms 的 Python 启动从"闭爪关键路径"挪到"已经夹住之后"。
: > "$B/g3-mock-lift.log"
MOCK_LOG="$B/g3-mock-lift.log" \
  $runner "$plan" --once --grasp-xy 120.5,-30.0 --teaching-table "$teaching" \
  --resume lift --grip-hold 2360 --six-cli "python3 $mock_ok" \
  --single-cli "python3 $mock_gripper" >"$B/g3-lift.out" 2>&1
grep -q '^G3_STEP name=grasp result=SKIPPED elapsed_ms=0 reason=resume_lift' "$B/g3-lift.out"
grep -q '^G3_STEP name=lift result=OK' "$B/g3-lift.out"
grep -q 'gripper_hold=2360' "$B/g3-lift.out"
# 闭爪（target 2200）绝不能再发一次：已经合上了，重发只会多花 1.4 s
if grep -q -- '--target 2200' "$B/g3-mock-lift.log"; then
  echo 'resume lift re-sent the close command' >&2; exit 1
fi
# 夹爪只应出现一次（place 的张开 2500）
[[ $(grep -c ' move --id 6 ' "$B/g3-mock-lift.log") -eq 1 ]]
[[ $(grep -c ' move-six ' "$B/g3-mock-lift.log") -eq 4 ]]

# ── 11) --resume lift 缺 --grip-hold 必须报参数错误 ──
if $runner "$plan" --once --grasp-xy 120.5,-30.0 --teaching-table "$teaching" \
    --resume lift --six-cli "python3 $mock_ok" \
    --single-cli "python3 $mock_gripper" >"$B/g3-lift-nohold.out" 2>&1; then
  echo '--resume lift without --grip-hold was accepted' >&2; exit 1
fi

# ── 12) --resume place：闭爪和抬升都已由 server 的 C 快路径做完，runner 从 place 起 ──
# 这是"取消咬合后空档"的一刀：臂不再被传送带拽着对抗 ~1.8 s。
: > "$B/g3-mock-place.log"
MOCK_LOG="$B/g3-mock-place.log" \
  $runner "$plan" --once --grasp-xy 120.5,-30.0 --teaching-table "$teaching" \
  --resume place --grip-hold 2360 --six-cli "python3 $mock_ok" \
  --single-cli "python3 $mock_gripper" >"$B/g3-place.out" 2>&1
grep -q '^G3_STEP name=lift result=SKIPPED elapsed_ms=0 reason=resume_place' "$B/g3-place.out"
grep -q '^G3_STEP name=place result=OK' "$B/g3-place.out"
grep -q 'gripper_hold=2360' "$B/g3-place.out"
# lift 不许再发一次六轴命令：只剩 place / retreat / exit 三条
[[ $(grep -c ' move-six ' "$B/g3-mock-place.log") -eq 3 ]]
# 闭爪（target 2200）绝不能再发
if grep -q -- '--target 2200' "$B/g3-mock-place.log"; then
  echo 'resume place re-sent the close command' >&2; exit 1
fi

# ── 13) --grasp-id2-offset：只改 approach/grasp 的 ID2，其它轴不动 ──
$runner "$plan" --once --dry-run --grasp-xy 120.5,-30.0 \
  --teaching-table "$teaching" --grasp-id2-offset -50 \
  --six-cli "python3 $mock_ok" --single-cli "python3 $mock_gripper" \
  >"$B/g3-id2offset.out" 2>&1
grep -q 'G3_INFO grasp ID2 offset -50' "$B/g3-id2offset.out"
# 表里 120.5 那一点 ID2=1111，减 50 应为 1061；ID1/ID3 保持原值
grep -q -- '--axis 1:2222:500:10' "$B/g3-id2offset.out"
grep -q -- '--axis 2:1061:500:10' "$B/g3-id2offset.out"
grep -q -- '--axis 3:2777:500:10' "$B/g3-id2offset.out"

echo RTCS_G3_STATION_RUNNER_GUARD_PASS
