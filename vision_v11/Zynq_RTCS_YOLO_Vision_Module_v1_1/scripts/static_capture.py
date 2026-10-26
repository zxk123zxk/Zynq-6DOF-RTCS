#!/usr/bin/env python3
"""静态抓取（上位机侧）：相机出点 → 稳定 0.5 s → UDP 发给板端 → 等回执。

一条命令即"static capture"：

    .\env.cmd scripts\static_capture.py --host 192.168.1.10

判据（用户 2026-10-26 定）：
  * 坐标**精确到 mm 个位**（`round` 到整数），浮点只进日志不进协议；
  * 同一整数坐标**连续保持 ≥500 ms** 才算有效，随即触发抓取；
  * 触发后**等回执**再继续；回执里带 `grip=contact|empty`，夹空不再算成功。

三条防误触发的设计（都是踩过的坑）：
  1. **执行期间不检测**：板端一动，夹爪会进画面（还被误检成 Cube），边跑边测必错。
  2. **回执后要求"目标消失 ≥0.8 s"才重新武装**：否则抓失败时方块还在，会原地连续触发。
  3. **软 ROI + 最高置信度**：只在标定带面内选目标，排除夹爪/背景误检。

只负责出点与传输，不碰舵机。协议见 `scripts/udp_grasp_server.py` 顶部注释。
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grasp_point as gp
from vision.detector import DEFAULT_MODEL, Detector
from vision.plane_calibration import DEFAULT_PATH, PlaneCalibration

RUNS_ROOT = Path(__file__).resolve().parents[3] / "vision_runs"
DEFAULT_PORT = 47800


def round_mm(value: float) -> int:
    """精确到 mm 个位。协议里只传整数——浮点留着进日志做误差分析。"""
    return int(round(value))


def wait_stable(camera, detector, cal, cls, *, stable_ms: int, min_samples: int,
                max_wait_s: float, require_clear_first: bool):
    """等到一个"连续 stable_ms 不变的整数坐标"。

    返回 dict 或 (None, 原因)。`require_clear_first` 用于每轮结束后重新武装：
    必须先看到"画面里没有目标"（方块已被抓走或被拿走），才接受新的触发点。
    """
    cand = None
    first_seen = None
    samples = 0
    raw_pairs = []
    cleared_since = None
    t_start = time.monotonic()
    while time.monotonic() - t_start < max_wait_s:
        frame = camera.read()
        try:
            result = detector.detect(frame)
        except ValueError:
            continue
        target, n_all, margin = gp.pick_target(result, cls, cal)
        now = time.monotonic()
        if target is None:
            cand, samples, raw_pairs = None, 0, []
            if cleared_since is None:
                cleared_since = now
            if require_clear_first and (now - cleared_since) >= 0.8:
                require_clear_first = False
            continue
        cleared_since = None
        if require_clear_first:
            # 上一轮的方块还在画面里：只等它消失，不拿它当新目标
            continue
        x_mm, y_mm = cal.to_mm(target.center_x, target.center_y)
        key = (round_mm(x_mm), round_mm(y_mm))
        if key != cand:
            cand, first_seen, samples, raw_pairs = key, now, 1, [(x_mm, y_mm)]
            continue
        samples += 1
        raw_pairs.append((x_mm, y_mm))
        if (now - first_seen) * 1000.0 >= stable_ms and samples >= min_samples:
            return {
                "x_mm": key[0], "y_mm": key[1],
                "x_raw": round(sum(p[0] for p in raw_pairs) / len(raw_pairs), 2),
                "y_raw": round(sum(p[1] for p in raw_pairs) / len(raw_pairs), 2),
                "stable_ms": int((now - first_seen) * 1000),
                "samples": samples,
                "conf": round(target.confidence, 3),
                "conf_margin": None if margin is None else round(margin, 3),
                "detections": n_all,
            }, None
    return None, "no_stable_target"


def send_and_wait(sock, host: str, port: int, request: dict, timeout_s: float,
                  retries: int):
    """发一条请求并等回执；同一 seq 重发，板端按 seq 去重。"""
    payload = json.dumps(request, ensure_ascii=False).encode()
    last_error = None
    for _ in range(retries):
        sock.sendto(payload, (host, port))
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                data, _addr = sock.recvfrom(8192)
            except socket.timeout:
                last_error = "reply_timeout"
                break
            try:
                reply = json.loads(data.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if reply.get("seq") == request["seq"]:
                return reply, None
        last_error = "reply_timeout"
    return None, last_error


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", required=True, help="板端 IP")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--stable-ms", type=int, default=500, help="稳定多久算有效（默认 500）")
    parser.add_argument("--min-samples", type=int, default=2, help="至少几帧参与判定")
    parser.add_argument("--max-trials", type=int, default=0, help="0 = 不设上限")
    parser.add_argument("--wait-s", type=float, default=120.0, help="单轮等目标的最长时间")
    parser.add_argument("--reply-timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--y-tol", type=float, default=6.0, help="y 偏离车道的告警阈值")
    parser.add_argument("--no-send", action="store_true", help="只出点不发（对数据链路用）")
    parser.add_argument("--log", type=Path, help="逐轮 JSONL；默认写 vision_runs/static_capture_<日期>/")
    parser.add_argument("--camera-index", type=int, default=gp.DEFAULT_CAMERA_INDEX)
    parser.add_argument("--backend", choices=("dshow", "msmf", "any"), default="dshow")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--class-name", choices=tuple(gp.CLASS_FILTER), default="any")
    parser.add_argument("--teaching-table", type=Path, default=gp.DEFAULT_TABLE)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args(argv)

    if args.log is None:
        args.log = RUNS_ROOT / f"static_capture_{time.strftime('%Y%m%d')}" / "trials.jsonl"

    try:
        calibration = PlaneCalibration.load(args.calibration)
        detector = Detector(args.model, device="cpu", conf=args.conf)
        camera = gp.open_camera(args.camera_index, args.backend, None, False)
    except (OSError, ValueError, RuntimeError, FileNotFoundError) as error:
        print(f"STATIC_CAPTURE_FAIL stage=init {error}", file=sys.stderr)
        return 3

    lane = gp.load_lane(args.teaching_table)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    print(f"STATIC_CAPTURE_READY host={args.host}:{args.port} stable_ms={args.stable_ms} "
          f"lane_y={None if not lane else lane['y_med']} "
          f"x_range={None if not lane else (lane['x_lo'], lane['x_hi'])}")
    if args.no_send:
        print("STATIC_CAPTURE_MODE no_send（只打印不发送）")

    seq = 0
    done = 0
    require_clear = False
    try:
        while args.max_trials == 0 or done < args.max_trials:
            point, why = wait_stable(camera, detector, calibration,
                                     gp.CLASS_FILTER[args.class_name],
                                     stable_ms=args.stable_ms, min_samples=args.min_samples,
                                     max_wait_s=args.wait_s, require_clear_first=require_clear)
            if point is None:
                print(f"STATIC_CAPTURE_WAIT {why}（继续等）")
                continue

            warnings = []
            if lane and not lane["x_lo"] <= point["x_mm"] <= lane["x_hi"]:
                warnings.append(f"x_outside_taught {lane['x_lo']:.0f}..{lane['x_hi']:.0f}"
                                f"（板端会夹端点）")
            if lane and abs(point["y_mm"] - lane["y_med"]) > args.y_tol:
                warnings.append(f"y_off_lane {point['y_mm'] - lane['y_med']:+.0f}mm"
                                f"（表只有 y={lane['y_med']:.0f} 一条车道，落点会偏）")

            seq += 1
            print(f"STATIC_CAPTURE_STABLE seq={seq} x={point['x_mm']} y={point['y_mm']} "
                  f"stable_ms={point['stable_ms']} samples={point['samples']} "
                  f"conf={point['conf']} raw=({point['x_raw']},{point['y_raw']})"
                  + ("" if not warnings else " WARN " + "; ".join(warnings)))
            for line in warnings:
                print(f"STATIC_CAPTURE_WARN {line}", file=sys.stderr)

            record = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "seq": seq, **point,
                      "warnings": warnings, "sent": not args.no_send}
            if args.no_send:
                print(f"STATIC_CAPTURE_DRYRUN would_send x={point['x_mm']} y={point['y_mm']}")
                _append(args.log, {**record, "reply": None})
                done += 1
                require_clear = True
                continue

            request = {"cmd": "grasp", "seq": seq, "x": point["x_mm"], "y": point["y_mm"],
                       "stable_ms": point["stable_ms"], "samples": point["samples"],
                       "ts": record["timestamp"]}
            t_send = time.monotonic()
            reply, error = send_and_wait(sock, args.host, args.port, request,
                                         args.reply_timeout, args.retries)
            rtt = int((time.monotonic() - t_send) * 1000)
            if reply is None:
                print(f"STATIC_CAPTURE_FAIL seq={seq} {error}（板端无回执）", file=sys.stderr)
                _append(args.log, {**record, "reply": None, "error": error})
            else:
                ok = bool(reply.get("ok"))
                grip = reply.get("grip")
                verdict = ("HIT" if ok and grip == "contact" else
                           "EMPTY" if ok and grip == "empty" else "FAIL")
                print(f"STATIC_CAPTURE_RESULT seq={seq} verdict={verdict} grip={grip} "
                      f"position={reply.get('position')} cycle_ms={reply.get('cycle_ms')} "
                      f"rtt_ms={rtt}")
                _append(args.log, {**record, "reply": reply, "verdict": verdict, "rtt_ms": rtt})
            done += 1
            # 板端动过一次：要求画面先"清空"再重新武装，避免对同一条方块重复触发
            require_clear = True
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nSTATIC_CAPTURE_STOP keyboard_interrupt")
    finally:
        camera.close()
        sock.close()
    print(f"STATIC_CAPTURE_SUMMARY trials={done} log={args.log}")
    return 0


def _append(path: Path, record: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"STATIC_CAPTURE_WARN log_failed {error}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
