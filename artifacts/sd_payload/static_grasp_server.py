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

只认三个 cmd（其它行忽略并提示，不当作命令执行）：

| cmd | 做什么 | 谁发 |
| --- | --- | --- |
| `static_capture` | 一轮完整七步抓取 | `capture_agent.py` |
| `dynamic_stage` | 走到拦截位、夹爪保持张开，然后返回（约 2 s） | `g5_dynamic_trigger.py` |
| `dynamic_close` | **先用 C 单轴命令快速闭爪**，再让 runner 从 lift 起做 lift/place/retreat/exit | 同上，物块越线时发 |

`dynamic_close` 可以带一个 `grip` 对象覆盖闭爪参数：

    {"cmd":"dynamic_close","x_mm":350,"y_mm":36,
     "grip":{"target":2200,"speed":1500,"observe_ms":600}}

**为什么闭爪不让 runner 做**：runner 每次启动要 ~880 ms（Python 启动 + 载计划 + 校验）。
2026-10-29 实测 `arm_ms − cycle_ms = 861~882 ms`（7 次），这在 67 mm/s 下等于物块走 59 mm
——正好是"从虎口走过去"。所以闭爪走编译好的 C 二进制（spawn 几十毫秒），
那 880 ms 的启动被挪到"已经夹住之后"，不再吃掉抓取时机。

回包里一定带 `cmd` 字段——PC 侧靠它把"上一条的回包"和"这一条的回包"分开。

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
# 板端单轴 C 命令：动态闭爪走它，不经过 Python runner。
SINGLE_CLI = "rtcs-pl-g2"
# 空夹判据与 runner 共用同一份实现；抬升走 fast_path（同样是直接调 C 六轴命令）。
sys.path.insert(0, str(ROOT / "scripts"))
from g3_station_runner import judge_gripper  # noqa: E402
from fast_path import fast_lift  # noqa: E402

# 示教表已覆盖的区间；只用于告警，不用于拦截。
TAUGHT_X = (295.0, 420.0)
# runner 一轮的最长容忍时间：实测 7.4~8.9 s，给到 90 s 足够覆盖故障恢复。
RUNNER_TIMEOUT_S = 90
# 动态拦截命令：坐标校验与 static_capture 完全共用，只是给 runner 切不同的两刀。
#   dynamic_stage —— 只走到拦截位、夹爪保持张开（约 2 s），臂守着等物块
#   dynamic_close —— 先由 server 直接调 C 单轴命令闭爪，再让 runner 从 lift 起搬运
# 为什么闭爪不让 runner 做：runner 每次启动要 ~880 ms（Python 启动 + 载计划 + 校验）。
# 2026-10-29 实测 arm_ms − cycle_ms = 861~882 ms（7 次），这段死时间正好等于
# "物块从虎口走过去"的距离（67 mm/s × 0.88 s ≈ 59 mm），是夹空的主因之一。
# C 单轴命令是编译好的二进制，spawn 只要几十毫秒。
DYNAMIC_EXTRA = {"dynamic_stage": ("--stop-after", "grasp")}
# fast-close 的默认开合参数；PC 可以在 dynamic_close 包里用 "grip" 字段覆盖。
# observe_ms 有下限 1000（rtcs-pl-g2 的 --observe-ms 接受 1000..10000 且必须 100 的倍数）。
# **踩过的坑**：给 600 会被 C 命令行直接判参数错误，一条帧都不发出去，
# 表现是 grip=fault、位置读回等于命令目标，然后 lift 多轴联动把物块扫下带。
DEFAULT_GRIP_CLOSE = {"target": 2200, "speed": 1500, "observe_ms": 1000}
GRIP_OBSERVE_MIN_MS = 1000


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
        elif line.startswith("ERR ") or " result=FAIL " in line \
                or line.startswith("G3_PLAN_REJECTED"):
            if verdict["fault"] is None:
                verdict["fault"] = line.strip()
    return verdict


def run_cycle(x_mm: float, y_mm: float, args, extra: tuple = ()) -> dict:
    """调状态机跑一轮，返回结论字典（含整段日志，供证据留痕）。

    ``extra`` 透传给 runner：动态拦截用 ``--stop-after grasp``（只到位不闭爪）与
    ``--resume close``（已在位，只闭爪+搬运）切两刀，其余步骤完全复用。
    """
    argv = [sys.executable, str(RUNNER), str(args.plan),
            "--uio", args.uio,
            "--grasp-xy", "%.2f,%.2f" % (x_mm, y_mm),
            "--teaching-table", str(args.teaching_table),
            "--once"] + list(extra)
    if args.dry_run:
        argv.append("--dry-run")
    # arm_ms 只量到子进程退出，量不到"收到 → 起进程 → 第一帧发出去"这段。
    # 这三处 mono_ms 用的是 CLOCK_MONOTONIC（跨进程同一时钟），与子进程打印的
    # G3_T0 / G3_STEP elapsed_ms 可以直接相减，动态抓取的提前量就是这么标出来的。
    log("ARM_CMD mono_ms=%.1f " % (time.monotonic() * 1000.0) + " ".join(argv))
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
    log("GRASP_RESULT mono_ms=%.1f ok=%s success=%s grip=%s grip_pos=%s cycle_ms=%s arm_ms=%s fault=%s"
        % (time.monotonic() * 1000.0, verdict.get("ok"), verdict.get("success"),
           verdict.get("grip"), verdict.get("gripper_position"), verdict.get("cycle_ms"),
           verdict.get("arm_ms"), verdict.get("fault")))
    tail = [line for line in verdict.get("log", "").splitlines()
            if line.startswith(("G3_T0", "G3_STEP", "G3_CYCLE", "G3_WARN", "G3_ABORT"))]
    for line in tail[-12:]:
        log("  " + line)
    if not verdict.get("ok"):
        # 失败时把原始输出的尾部原样打出来。只按 G3_* 前缀过滤会把
        # G3_PLAN_REJECTED（走 stderr）和 Python traceback 全吃掉，现场只看到
        # "success=None fault=None"，像是什么都没发生——2026-10-29 为此白跑一趟：
        # 真正的原因是板端 Python 版本下的语法错误，一行都没露出来。
        raw = [line for line in verdict.get("log", "").splitlines() if line.strip()]
        for line in raw[-10:]:
            log("  RAW " + line[:200])
    if verdict.get("grip") == "empty":
        log("SERVER_WARN 这一轮 grip=empty：八步都成功，但夹爪合到底没夹到东西")
    log("SERVER_READY 等待下一条命令")


COMMANDS = ("static_capture", "dynamic_stage", "dynamic_close")


def fast_close(args, packet: dict) -> dict:
    """直接调 C 单轴命令闭合夹爪，返回 ok / semantic / position / elapsed_ms。

    动态拦截的关键路径。从"server 收到这条命令"到"舵机开始动"只有一次进程 spawn
    （几十毫秒），而不是 runner 的 ~880 ms——那 0.88 s 在 67 mm/s 下等于物块走 59 mm。
    """
    grip = packet.get("grip")
    grip = grip if isinstance(grip, dict) else {}
    action = {"command": "close",
              "target_count": int(grip.get("target", DEFAULT_GRIP_CLOSE["target"])),
              "speed_raw": int(grip.get("speed", DEFAULT_GRIP_CLOSE["speed"]))}
    observe_ms = int(grip.get("observe_ms", DEFAULT_GRIP_CLOSE["observe_ms"]))
    if observe_ms < GRIP_OBSERVE_MIN_MS:
        # 只告警并抬到下限：C 命令会直接拒掉小于 1000 的窗口，发出去等于白白夹不中。
        log("SERVER_WARN observe_ms=%d 低于下限 %d，按 %d 下发"
            % (observe_ms, GRIP_OBSERVE_MIN_MS, GRIP_OBSERVE_MIN_MS))
        observe_ms = GRIP_OBSERVE_MIN_MS
    argv = [SINGLE_CLI, "--uio", args.uio, "move", "--id", "6",
            "--target", str(action["target_count"]),
            "--speed-raw", str(action["speed_raw"]),
            "--time-raw", "10",
            "--observe-ms", str(observe_ms), "--execute"]
    if args.dry_run:
        log("DRY_RUN_FAST_CLOSE " + " ".join(argv))
        return {"ok": True, "semantic": "DRY_RUN", "position": None, "elapsed_ms": 0}
    log("FAST_CLOSE mono_ms=%.1f " % (time.monotonic() * 1000.0) + " ".join(argv))
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "semantic": "FAULT", "position": None,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "error": str(error)}
    output = (proc.stdout or "") + (proc.stderr or "")
    ok, semantic, position = judge_gripper(output, action)
    return {"ok": ok, "semantic": semantic, "position": position,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "output": output}


def handle_close(packet: dict, args, x_mm: float, y_mm: float,
                 warnings: list[str]) -> dict:
    """dynamic_close：先快路径闭爪，再让 runner 从 lift 起搬运。

    拆成"闭爪（C，几十毫秒）+ 搬运（Python，880 ms 启动）"：启动开销被挪到
    "已经夹住之后"，不再吃掉抓取时机。撞过的反面：闭爪也走 runner 时，
    命令发出到咬合要 ~1.4 s，物块早过去了。
    """
    for warning in warnings:
        log("SERVER_WARN " + warning)
    close = fast_close(args, packet)
    log("FAST_CLOSE_RESULT ok=%s semantic=%s position=%s elapsed_ms=%s"
        % (close["ok"], close["semantic"], close["position"], close["elapsed_ms"]))
    if not close["ok"]:
        # 失败时把 C 命令的输出原样打出来。10-29 踩过：observe_ms 给 600 被 C 判
        # 参数错误，一条帧都没发，而日志只说 grip=fault，看不出是参数被拒。
        for line in (close.get("output") or close.get("error") or "").splitlines()[-6:]:
            log("  RAW_CLOSE " + line[:200])
    hold = close["position"]
    if hold is None:
        # 读不到接触位置就退回命令目标（与 runner 的 gripper_hold_from_command 一致）。
        # 不重发一次闭爪：重复闭合只会再多花 1.4 s，而且夹爪已经合上了。
        grip = packet.get("grip") if isinstance(packet.get("grip"), dict) else {}
        hold = int(grip.get("target", DEFAULT_GRIP_CLOSE["target"]))
        log("SERVER_WARN gripper_hold_from_command target=%d" % hold)

    lift = fast_lift(args.uio, args.plan, args.teaching_table, x_mm, y_mm, hold,
                     args.dry_run, log)
    log("FAST_LIFT_RESULT ok=%s elapsed_ms=%s targets=%s"
        % (lift["ok"], lift["elapsed_ms"], lift.get("targets")))
    if not lift["ok"]:
        for line in (lift.get("output") or lift.get("error") or "").splitlines()[-6:]:
            log("  RAW_LIFT " + line[:200])

    verdict = run_cycle(x_mm, y_mm, args,
                        ("--resume", "place", "--grip-hold", str(hold)))
    tail = [line for line in verdict.get("log", "").splitlines()
            if line.startswith(("G3_T0", "G3_STEP", "G3_CYCLE", "G3_WARN", "G3_ABORT"))]
    for line in tail[-8:]:
        log("  " + line)
    if not verdict.get("ok"):
        raw = [line for line in verdict.get("log", "").splitlines() if line.strip()]
        for line in raw[-8:]:
            log("  RAW " + line[:200])

    semantic = str(close["semantic"]).lower()
    ok = bool(close["ok"]) and bool(lift["ok"]) and bool(verdict.get("ok"))
    log("GRASP_RESULT mono_ms=%.1f ok=%s grip=%s grip_pos=%s cycle_ms=%s close_ms=%s "
        "lift_ms=%s"
        % (time.monotonic() * 1000.0, ok, semantic, hold, verdict.get("cycle_ms"),
           close["elapsed_ms"], lift["elapsed_ms"]))
    log("SERVER_READY 等待下一条命令")
    return {"ok": ok, "success": 1 if ok else 0, "grip": semantic,
            "gripper_position": hold, "cycle_ms": verdict.get("cycle_ms"),
            "arm_ms": (close["elapsed_ms"] + lift["elapsed_ms"]
                       + int(verdict.get("arm_ms") or 0)),
            "fault": verdict.get("fault"), "close_ms": close["elapsed_ms"],
            "lift_ms": lift["elapsed_ms"],
            "x_mm": x_mm, "y_mm": y_mm, "cmd": "dynamic_close"}


def handle(packet: dict, args) -> dict:
    """一条指令的完整处理：校验 → 执行 → 回报。"""
    cmd = packet.get("cmd")
    if cmd not in COMMANDS:
        log("SERVER_IGNORE 只认 %s，收到 %r" % (" / ".join(COMMANDS), cmd))
        return {"ok": False, "error": "unknown_cmd", "cmd": cmd}

    try:
        x_mm, y_mm, warnings = validate(packet)
    except ValueError as error:
        log("SERVER_ERROR 协议错误：%s" % error)
        return {"ok": False, "error": str(error), "cmd": cmd}

    log("SERVER_ACCEPT mono_ms=%.1f cmd=%s x_mm=%.2f y_mm=%.2f stable_s=%s conf=%s "
        "n=%s from=%s"
        % (time.monotonic() * 1000.0, cmd, x_mm, y_mm, packet.get("stable_s"),
           packet.get("conf"), packet.get("n"), packet.get("source", "?")))
    if cmd == "dynamic_close":
        return handle_close(packet, args, x_mm, y_mm, warnings)

    extra = list(DYNAMIC_EXTRA.get(cmd, ()))
    offset = packet.get("id2_offset")
    if isinstance(offset, int) and offset and cmd == "dynamic_stage":
        # 现场指定的 ID2 偏移（负值 = 夹取点抬高一点），只作用于拦截位，不动静态路径。
        extra += ["--grasp-id2-offset", str(offset)]
    verdict = run_cycle(x_mm, y_mm, args, extra)
    report(packet, verdict, warnings)
    reply = {key: verdict.get(key) for key in
             ("ok", "success", "grip", "gripper_position", "cycle_ms", "arm_ms", "fault", "error")}
    reply.update({"x_mm": x_mm, "y_mm": y_mm, "cmd": cmd})
    return reply


def serve_stdin(args) -> int:
    log("SERVER_READY source=stdin 等待 static_capture / dynamic_stage / dynamic_close（Ctrl-C 退出）")
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
    log("SERVER_READY source=udp %s:%d 等待 static_capture / dynamic_stage / dynamic_close（Ctrl-C 退出）"
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
