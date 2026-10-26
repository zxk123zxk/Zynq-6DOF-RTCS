#!/usr/bin/env python3
"""板端 UDP 抓取服务：收一行 JSON → 跑一轮七步 → 回执。

板上跑（**必须 sudo**，要开 UIO）：

    sudo python3 scripts/udp_grasp_server.py --port 47800

PC 侧对应 `vision_v11/.../scripts/static_capture.py`。

**协议（UDP，请求/回执各一行 JSON，UTF-8）**

请求：
    {"cmd":"grasp","seq":1,"x":333,"y":36,"stable_ms":520,"samples":3,"ts":"..."}

回执：
    {"seq":1,"ok":true,"success":1,"grip":"contact","position":2371,
     "cycle_ms":7941,"clamped":false,"error":null}

**三条约定**

1. **按 seq 去重**：PC 收不到回执会原样重发同一 seq。收到已处理过的 seq 直接回缓存，
   绝不重复运动——UDP 会丢包，但机械臂不能因此抓两次。
2. **串行执行**：一轮没跑完就再来一条命令，只回 `busy`，不排队、不并发。
3. **越界只告警不拒绝**：x 出界的判断交给 `g3_station_runner`（它两端夹住并打
   `G3_WARN grasp-xy ... outside taught range`），这里只把结果标成 `clamped=true`
   回报给 PC，让统计能区分"真抓"和"夹端点抓的"。
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "config" / "g3_station_plan.json"
DEFAULT_TABLE = ROOT / "config" / "grasp_teaching_table.json"
MAX_RUN_S = 120

RE_CYCLE = re.compile(r"^G3_CYCLE end=\d+ success=(\d+) grip=(\w+)", re.M)
RE_GRIP = re.compile(r"^G3_STEP name=grasp\.gripper result=(\w+)(?:.*?position=(\d+))?", re.M)
RE_TIMING = re.compile(r"^G3_CYCLE timing elapsed_ms=(\d+)", re.M)
RE_CLAMP = re.compile(r"outside taught range", re.M)


def parse_runner_output(output: str) -> dict:
    """把板端 CLI 的文本输出翻译成回执字段。看不懂的一律如实报，不猜。"""
    result = {"ok": False, "success": 0, "grip": None, "position": None,
              "cycle_ms": None, "clamped": bool(RE_CLAMP.search(output)), "error": None}
    if "G3_PLAN_REJECTED" in output:
        line = next((l for l in output.splitlines() if l.startswith("G3_PLAN_REJECTED")), "")
        result["error"] = line.strip() or "plan_rejected"
        return result
    if "G3_ABORT" in output:
        result["error"] = "abort_exit_recovery_failed"
        return result
    grip = RE_GRIP.search(output)
    if grip:
        result["grip"] = grip.group(1).lower()
        if grip.group(2) is not None:
            result["position"] = int(grip.group(2))
    cycle = RE_CYCLE.search(output)
    if cycle:
        result["success"] = int(cycle.group(1))
        result["grip"] = cycle.group(2)
        result["ok"] = result["success"] == 1
    timing = RE_TIMING.search(output)
    if timing:
        result["cycle_ms"] = int(timing.group(1))
    if not cycle:
        result["error"] = result["error"] or "no_cycle_result"
    elif not result["ok"]:
        fault = next((l.strip() for l in output.splitlines() if l.startswith("G3_STEP")
                      and "result=FAIL" in l), "")
        result["error"] = fault or "cycle_failed"
    return result


def validate_request(raw: bytes) -> tuple[dict | None, str | None]:
    try:
        request = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "bad_json"
    if not isinstance(request, dict):
        return None, "not_object"
    if request.get("cmd") != "grasp":
        return None, "unsupported_cmd"
    seq = request.get("seq")
    if not isinstance(seq, int) or seq < 1:
        return None, "bad_seq"
    for axis in ("x", "y"):
        value = request.get(axis)
        if not isinstance(value, (int, float)) or value != value or not -1000 < value < 1000:
            return None, f"bad_{axis}"
    return request, None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=47800)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--uio", default="/dev/uio0")
    parser.add_argument("--runner", default=str(ROOT / "scripts" / "g3_station_runner.py"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true",
                        help="把 --dry-run 透传给状态机：只校验计划、不发运动帧（联调用）")
    args = parser.parse_args(argv)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.bind, args.port))
    cached: dict[int, dict] = {}
    print(f"UDP_GRASP_READY bind={args.bind}:{args.port} dry_run={args.dry_run} "
          f"plan={args.plan.name} table={args.table.name}", flush=True)

    while True:
        try:
            raw, addr = sock.recvfrom(8192)
        except KeyboardInterrupt:
            print("UDP_GRASP_STOP keyboard_interrupt", flush=True)
            return 0
        request, why = validate_request(raw)
        if request is None:
            print(f"UDP_GRASP_BAD from={addr[0]} reason={why}", flush=True)
            sock.sendto(json.dumps({"seq": None, "ok": False, "error": why}).encode(), addr)
            continue

        seq = request["seq"]
        if seq in cached:
            print(f"UDP_GRASP_DEDUPE seq={seq}（重发，直接回缓存）", flush=True)
            sock.sendto(json.dumps(cached[seq], ensure_ascii=False).encode(), addr)
            continue

        x, y = request["x"], request["y"]
        print(f"UDP_GRASP_RECV seq={seq} x={x} y={y} stable_ms={request.get('stable_ms')} "
              f"samples={request.get('samples')} from={addr[0]}", flush=True)
        parts = [args.python, args.runner, str(args.plan), "--uio", args.uio,
                 "--grasp-xy", f"{x},{y}", "--teaching-table", str(args.table), "--once"]
        if args.dry_run:
            parts.append("--dry-run")
        t0 = time.monotonic()
        try:
            proc = subprocess.run(parts, capture_output=True, text=True, timeout=MAX_RUN_S)
            output = (proc.stdout or "") + (proc.stderr or "")
            reply = parse_runner_output(output)
        except subprocess.TimeoutExpired:
            reply = {"ok": False, "success": 0, "grip": None, "position": None,
                     "cycle_ms": None, "clamped": False, "error": "runner_timeout"}
            output = ""
        reply["seq"] = seq
        reply["runner_ms"] = int((time.monotonic() - t0) * 1000)
        reply["dry_run"] = bool(args.dry_run)   # 干跑时 grip 也是假的，必须标出来
        cached[seq] = reply
        if len(cached) > 200:                       # 只留最近的回执，别把 RAM 吃满
            cached = dict(sorted(cached.items())[-100:])
        print(f"UDP_GRASP_REPLY seq={seq} ok={reply['ok']} grip={reply['grip']} "
              f"position={reply['position']} cycle_ms={reply['cycle_ms']} "
              f"clamped={reply['clamped']} error={reply['error']}", flush=True)
        if not reply["ok"] and output:
            for line in output.splitlines():
                if line.startswith(("G3_STEP", "G3_PLAN_REJECTED", "G3_ABORT", "ERR ")):
                    print("  " + line, flush=True)
        sock.sendto(json.dumps(reply, ensure_ascii=False).encode(), addr)


if __name__ == "__main__":
    sys.exit(main())
