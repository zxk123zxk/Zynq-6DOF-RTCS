#!/usr/bin/env python3
"""板端接收端：收到视觉坐标就立刻跑一轮七步抓取。

**它是"上位机"的那一端**：坐标由 PC 侧 `capture_agent.py` 给出，本程序只负责
"收下 → 校验 → 调 g3_station_runner.py → 回报结果"。不碰相机、不做推理，
所以符合赛道的分工红线（策略/感知在 AI PC，实时执行在 PS/PL）。

两种取信方式（板端二选一）：

    sudo python3 scripts/static_grasp_server.py --source stdin          # 走控制台
    sudo python3 scripts/static_grasp_server.py --source udp --port 5005 # 走网口

`--source stdin` 是给"PC 与板子只有串口/终端"的场合准备的：本程序在前台占住
控制台的 stdin，PC 侧往串口写一行 JSON 就会被读到（此时 shell 不解释这行文本）。
`--source udp` 是首选，前提是板子与 PC 在同一网段（先 `ip addr` 确认）。

协议：一行 JSON，UTF-8，以换行结束。

    {"cmd":"static_capture","x_mm":333.42,"y_mm":36.08,"stable_s":0.72,...}

只认 `cmd="static_capture"`；其它行忽略并提示，不当作命令执行。
`--dry-run` 会把 `--dry-run` 透传给 runner：只打印命令、不产生运动帧，
用于**首次接通链路**时验证，不用于交付。

**不做硬门禁**：坐标越界、置信度低、目标不稳，只打印告警并照旧执行——
决定要不要跑由操作者看告警后决定（依据 CLAUDE.md 的约定）。
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "g3_station_runner.py"
PLAN = ROOT / "config" / "g3_station_plan.json"
TABLE = ROOT / "config" / "grasp_teaching_table.json"

# 示教表已覆盖的区间；只用于告警，不用于拦截。
TAUGHT_X = (295.0, 420.0)
# runner 一轮的最长容忍时间：实测 7.4~8.9 s，给到 90 s 足够覆盖故障恢复。
RUNNER_TIMEOUT_S = 90


def log(message: str) -> None:
    print(message, flush=True)


def parse_packet(text: str):
    """从一行文本里取出 JSON 对象；容忍前后有终端回显或提示符。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def validate(payload: dict) -> tuple[float, float, list[str]]:
    """取出 (x, y) 并给出告警清单。缺字段就抛错——这不是"告警"而是协议错误。"""
    for key in ("x_mm", "y_mm"):
        if not isinstance(payload.get(key), (int, float)):
            raise ValueError("missing or non-numeric %s" % key)
    x, y = float(payload["x_mm"]), float(payload["y_mm"])
    warnings = []
    if not TAUGHT_X[0] <= x <= TAUGHT_X[1]:
        warnings.append(
            "x=%.1f 不在示教区间 %.0f..%.0f：插值两端夹住，落点会偏 20 mm 以上"
            % (x, TAUGHT_X[0], TAUGHT_X[1]))
    if abs(y - 36.0) > 8.0:
        warnings.append("y=%.1f 偏离车道 36 超过 8 mm：y 不参与插值，偏差会全额落在落点上" % y)
    stable = payload.get("stable_s")
    if isinstance(stable, (int, float)) and stable < 0.5:
        warnings.append("stable_s=%.2f 短于 0.5 s" % stable)
    conf = payload.get("conf")
    if isinstance(conf, (int, float)) and conf < 0.45:
        warnings.append("conf=%.2f 偏低，可能误检" % conf)
    return x, y, warnings


def parse_verdict(output: str) -> dict:
    """从 runner 的输出里抽结论；抽不到就如实标 unknown，不猜。"""
    verdict = {"success": None, "grip": None, "cycle_ms": None,
               "gripper_position": None, "fault": None}
    for line in output.splitlines():
        if line.startswith("G3_CYCLE end=") and "success=" in line:
            for token in line.split():
                if token.startswith("success="):
                    verdict["success"] = int(token.split("=", 1)[1])
                elif token.startswith("grip="):
                    verdict["grip"] = token.split("=", 1)[1]
        elif line.startswith("G3_CYCLE timing"):
            for token in line.split():
                if token.startswith("elapsed_ms="):
                    verdict["cycle_ms"] = int(token.split("=", 1)[1])
        elif line.startswith("G3_STEP name=grasp.gripper"):
            for token in line.split():
                if token.startswith("position="):
                    verdict["gripper_position"] = int(token.split("=", 1)[1])
        elif line.startswith("ERR ") or " result=FAIL " in line:
            if verdict["fault"] is None:
                verdict["fault"] = line.strip()
    return verdict


def run_cycle(x_mm: float, y_mm: float, args) -> dict:
    """调状态机跑一轮，返回结论字典（含整段日志，供证据留痕）。"""
    argv = [sys.executable, str(RUNNER), str(args.plan),
            "--uio", args.uio,
            "--grasp-xy", "%.2f,%.2f" % (x_mm, y_mm),
            "--teaching-table", str(args.teaching_table),
            "--once"]
    if args.dry_run:
        argv.append("--dry-run")
    log("ARM_CMD " + " ".join(argv))
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=RUNNER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "runner_timeout_%ds" % RUNNER_TIMEOUT_S,
                "arm_ms": RUNNER_TIMEOUT_S * 1000, "log": ""}
    output = (proc.stdout or "") + (proc.stderr or "")
    verdict = parse_verdict(output)
    verdict["ok"] = proc.returncode == 0 and verdict["success"] == 1
    verdict["returncode"] = proc.returncode
    verdict["arm_ms"] = int((time.monotonic() - started) * 1000)
    verdict["log"] = output
    return verdict


def report(packet: dict, verdict: dict, warnings: list[str]) -> None:
    """人读结论（控制台）+ 机读结论（UDP 回包复用同一个 dict）。"""
    for warning in warnings:
        log("SERVER_WARN " + warning)
    log("GRASP_RESULT ok=%s success=%s grip=%s grip_pos=%s cycle_ms=%s arm_ms=%s fault=%s"
        % (verdict.get("ok"), verdict.get("success"), verdict.get("grip"),
           verdict.get("gripper_position"), verdict.get("cycle_ms"),
           verdict.get("arm_ms"), verdict.get("fault")))
    tail = [line for line in verdict.get("log", "").splitlines()
            if line.startswith(("G3_STEP", "G3_CYCLE", "G3_WARN", "G3_ABORT"))]
    for line in tail[-12:]:
        log("  " + line)
    if verdict.get("grip") == "empty":
        log("SERVER_WARN 这一轮 grip=empty：八步都成功，但夹爪合到底没夹到东西")
    log("SERVER_READY 等待下一条 static_capture")


def handle(packet: dict, args) -> dict:
    """一条指令的完整处理：校验 → 执行 → 回报。"""
    if packet.get("cmd") != "static_capture":
        log("SERVER_IGNORE 只认 cmd=static_capture，收到 %r" % (packet.get("cmd"),))
        return {"ok": False, "error": "unknown_cmd"}

    try:
        x_mm, y_mm, warnings = validate(packet)
    except ValueError as error:
        log("SERVER_ERROR 协议错误：%s" % error)
        return {"ok": False, "error": str(error)}

    log("SERVER_ACCEPT x_mm=%.2f y_mm=%.2f stable_s=%s conf=%s n=%s from=%s"
        % (x_mm, y_mm, packet.get("stable_s"), packet.get("conf"),
           packet.get("n"), packet.get("source", "?")))
    verdict = run_cycle(x_mm, y_mm, args)
    report(packet, verdict, warnings)
    reply = {key: verdict.get(key) for key in
             ("ok", "success", "grip", "gripper_position", "cycle_ms", "arm_ms", "fault", "error")}
    reply.update({"x_mm": x_mm, "y_mm": y_mm})
    return reply


def serve_stdin(args) -> int:
    log("SERVER_READY source=stdin 等待 static_capture（Ctrl-C 退出）")
    while True:
        line = sys.stdin.readline()
        if not line:
            log("SERVER_EXIT stdin 关闭")
            return 0
        packet = parse_packet(line)
        if packet is None:
            if line.strip():
                log("SERVER_IGNORE 不是 JSON：%r" % line.strip()[:80])
            continue
        reply = handle(packet, args)
        # 控制台式串口会回显我们发进去的那一行，PC 侧要靠 `REPLY ` 前缀把回包认出来。
        log("REPLY " + json.dumps(reply, ensure_ascii=False))


def serve_udp(args) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.bind, args.port))
    log("SERVER_READY source=udp %s:%d 等待 static_capture（Ctrl-C 退出）"
        % (args.bind, args.port))
    while True:
        data, peer = sock.recvfrom(4096)
        text = data.decode("utf-8", "replace")
        packet = parse_packet(text)
        if packet is None:
            log("SERVER_IGNORE 不是 JSON from %s：%r" % (peer[0], text[:80]))
            continue
        reply = handle(packet, args)
        try:
            sock.sendto((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"), peer)
        except OSError as error:
            log("SERVER_WARN 回包失败：%s" % error)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=("stdin", "udp"), default="stdin")
    parser.add_argument("--bind", default="0.0.0.0", help="UDP 监听地址")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--uio", default="/dev/uio0")
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--teaching-table", type=Path, default=TABLE)
    parser.add_argument("--dry-run", action="store_true",
                        help="透传给 runner：只打印命令、不产生运动帧（首连链路用）")
    args = parser.parse_args(argv)

    for path in (args.plan, args.teaching_table, RUNNER):
        if not path.exists():
            print("SERVER_ERROR 找不到 %s（板端要从 SD 拷齐 ~/rtcs）" % path, file=sys.stderr)
            return 2
    try:
        return serve_stdin(args) if args.source == "stdin" else serve_udp(args)
    except KeyboardInterrupt:
        log("SERVER_EXIT interrupted")
        return 0


if __name__ == "__main__":
    sys.exit(main())
