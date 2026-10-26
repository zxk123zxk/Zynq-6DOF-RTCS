"""PC 侧触发端：输入 `static capture` → 出点 → 稳定 0.5 s → 发给板端 → 回报结果。

这就是"人抄两个数"的自动化替代：**坐标不再经人手转抄**，而是由本程序直接送到
板端 `static_grasp_server.py`，收到后立刻跑已有的七步抓取。

稳定判据（`--stable-s 0.5 --tol-mm 2`）：连续采样中，取"末尾这一段 x/y 极差都 ≤ tol"
的最长后缀，它的时间跨度 ≥ stable_s 才算有效，坐标取这一段的中位数。
为什么要这个门槛：单帧抖动 ±2~4 px ≈ 1~2 mm，且刚放下的方块会被手带得轻微晃动；
"稳定半秒"把这两类噪声挡在门外，与竞赛要求一致。

三种传输（板端与 PC 之间怎么连就选哪个）：

    --udp 10.83.x.x:5005    首选：同一网段，板端起 --source udp
    --serial COM5           只有串口/终端时用，板端起 --source stdin
    （默认 stdout）          没有链路时退化为打印板端命令，等价于今天的人工流程

`stdout` 模式不是摆设：链路没通时它保证整个流程仍然可用，也是排障基线——
如果 stdout 能抓中、udp 抓不中，问题一定在链路上，不在视觉或机械臂。

用法：
    .\\env.cmd scripts\\capture_agent.py
    .\\env.cmd scripts\\capture_agent.py --udp 10.83.133.9:5005
    .\\env.cmd scripts\\capture_agent.py --once --json
"""
from __future__ import annotations

import argparse
import json
import socket
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grasp_point as gp
from vision.detector import DEFAULT_MODEL, Detector
from vision.plane_calibration import DEFAULT_PATH, PlaneCalibration

TRIGGERS = ("static capture", "static_capture", "capture", "grab")
BOARD_CMD = ("sudo python3 scripts/g3_station_runner.py config/g3_station_plan.json "
             "--uio /dev/uio0 --grasp-xy {x:.2f},{y:.2f} "
             "--teaching-table config/grasp_teaching_table.json --once")


class Sampler:
    """持续采样并判断"稳定"的那一段。"""

    def __init__(self, calibration: PlaneCalibration, stable_s: float, tol_mm: float,
                 min_samples: int = 3):
        self.calibration = calibration
        self.stable_s = stable_s
        self.tol_mm = tol_mm
        self.min_samples = min_samples
        self.samples: list[tuple[float, float, float, float]] = []  # (t, x, y, conf)
        self.last_seen = 0.0

    def add(self, now: float, x_mm: float, y_mm: float, conf: float) -> None:
        self.samples.append((now, x_mm, y_mm, conf))
        self.last_seen = now

    def drop_if_lost(self, now: float) -> None:
        """目标消失超过 0.4 s 就清空——否则"消失前的那段"会被当成稳定期。"""
        if self.samples and now - self.last_seen > 0.4:
            self.samples.clear()

    def prune(self, now: float, keep_s: float = 4.0) -> None:
        cutoff = now - keep_s
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.pop(0)

    def stable_window(self):
        """返回 (中位数 x, y, 跨度秒, 点数, 极差 x, 极差 y)；未稳定返回 None。

        从**最近的一小段**（3 帧）开始往前扩，取最先同时满足"极差 ≤ tol"和
        "跨度 ≥ stable_s"的那一段——这样响应最快；一旦某次扩展超出 tol 就停，
        因为再往前只会更宽。抖动过的头部会被自然丢掉（见单测"抖动后稳定"）。
        """
        if len(self.samples) < self.min_samples:
            return None
        best = None
        for start in range(len(self.samples) - self.min_samples, -1, -1):
            window = self.samples[start:]
            xs = [s[1] for s in window]
            ys = [s[2] for s in window]
            if max(xs) - min(xs) > self.tol_mm or max(ys) - min(ys) > self.tol_mm:
                break                    # 再往前更不可能满足，直接停
            span = window[-1][0] - window[0][0]
            best = (statistics.median(xs), statistics.median(ys), span, len(window),
                    max(xs) - min(xs), max(ys) - min(ys))
            if span >= self.stable_s:
                return best
        return None


def open_stack(args):
    calibration = PlaneCalibration.load(args.calibration)
    detector = Detector(args.model, device=args.device, imgsz=args.imgsz, conf=args.conf)
    camera = gp.open_camera(args.camera_index, args.backend, args.exposure,
                            args.auto_exposure)
    return calibration, detector, camera


def do_capture(args, calibration, detector, camera, sampler: Sampler):
    """抓一次点；稳定则返回 dict，超时返回 None（附原因）。"""
    cls = gp.CLASS_FILTER[args.class_name]
    started = time.monotonic()
    deadline = started + args.timeout
    attempts, frames, no_target = 0, 0, 0
    print("CAPTURE_START stable=%.2fs tol=%.1fmm timeout=%.1fs" %
          (args.stable_s, args.tol_mm, args.timeout), flush=True)

    while time.monotonic() < deadline:
        frame = camera.read()
        frames += 1
        now = time.monotonic()
        try:
            result = detector.detect(frame)
        except ValueError as error:
            print("CAPTURE_WARN detect_skipped %s" % error, file=sys.stderr, flush=True)
            continue
        target, n_all, margin = gp.pick_target(result, cls, calibration)
        if target is None:
            no_target += 1
            sampler.drop_if_lost(now)
            continue
        x_mm, y_mm = calibration.to_mm(target.center_x, target.center_y)
        sampler.add(now, x_mm, y_mm, target.confidence)
        sampler.prune(now)
        attempts += 1

        window = sampler.stable_window()
        if window:
            x_med, y_med, span, n, spread_x, spread_y = window
            return {
                "x_mm": round(x_med, 3), "y_mm": round(y_med, 3),
                "stable_s": round(span, 3), "n": n,
                "spread_mm": [round(spread_x, 3), round(spread_y, 3)],
                "conf": round(statistics.median(s[3] for s in sampler.samples[-n:]), 4),
                "conf_margin": None if margin is None else round(margin, 3),
                "frames": frames,
                "detect_ms": int(1000 * (now - started) / max(frames, 1)),
                "wait_s": round(now - started, 2),
                "detections_per_frame": n_all,
            }
        if attempts % 2 == 1:
            print("  sampling n=%d x=%.1f y=%.1f conf=%.2f" %
                  (len(sampler.samples), x_mm, y_mm, target.confidence), flush=True)

    print("CAPTURE_FAIL reason=timeout frames=%d no_target=%d samples=%d"
          % (frames, no_target, len(sampler.samples)), flush=True)
    if sampler.samples:
        xs = [s[1] for s in sampler.samples]
        ys = [s[2] for s in sampler.samples]
        print("CAPTURE_WARN 最近一段的极差 x=%.1f y=%.1f mm（阈值 %.1f）：目标在动，或框在跳"
              % (max(xs) - min(xs), max(ys) - min(ys), args.tol_mm), flush=True)
    return None


def send(args, packet: dict, point: dict) -> dict | None:
    """把坐标送出去；返回板端回包（stdout 模式返回 None）。"""
    payload = dict(packet)
    line = json.dumps(payload, ensure_ascii=False)

    if args.transport == "udp":
        host, _, port = args.udp.rpartition(":")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(args.reply_timeout)
        print("CAPTURE_SENT transport=udp %s:%s bytes=%d" % (host, port, len(line)),
              flush=True)
        try:
            sock.sendto(line.encode("utf-8"), (host, int(port)))
            data, _peer = sock.recvfrom(4096)
        except socket.timeout:
            print("CAPTURE_FAIL 板端 %.0fs 内没有回包：检查 --port、防火墙、板端是否在跑 server"
                  % args.reply_timeout, flush=True)
            return None
        except OSError as error:
            print("CAPTURE_FAIL udp %s（坐标已打印，可人工粘贴）" % error, flush=True)
            return None
        finally:
            sock.close()
        try:
            return json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            print("CAPTURE_WARN 回包不是 JSON：%r" % data[:120], flush=True)
            return None

    if args.transport == "serial":
        try:
            import serial
        except ImportError:
            print("CAPTURE_FAIL 没装 pyserial：在 venv 里 pip install pyserial",
                  flush=True)
            return None
        try:
            port = serial.Serial(args.serial, args.baud, timeout=1.0)
        except Exception as error:                       # 端口不存在/被占用
            print("CAPTURE_FAIL 打不开串口 %s：%s（先用终端程序关掉它，"
                  "控制台程序会独占端口）" % (args.serial, error), flush=True)
            return None
        lines: list[str] = []
        with port:
            port.write((line + "\n").encode("utf-8"))
            port.flush()
            print("CAPTURE_SENT transport=serial %s %d baud" % (args.serial, args.baud),
                  flush=True)
            reply, deadline = None, time.monotonic() + args.reply_timeout
            while time.monotonic() < deadline:
                raw = port.readline()
                if not raw:
                    continue
                text = raw.decode("utf-8", "replace").strip()
                if not text:
                    continue
                # 控制台会回显我们发进去的那行，也会混进提示符；只认带 "ok" 的 JSON。
                candidate = text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""
                if candidate:
                    try:
                        parsed = json.loads(candidate)
                    except ValueError:
                        parsed = None
                    if isinstance(parsed, dict) and "ok" in parsed:
                        reply = parsed
                        break
                lines.append(text)
        if lines:
            print("BOARD_LOG 前 %d 行板端输出：" % min(len(lines), 14), flush=True)
            for text in lines[:14]:
                print("  " + text[:160], flush=True)
        if reply is None:
            print("CAPTURE_FAIL 串口 %.0fs 内没等到 REPLY（板端 server 在跑吗？"
                  "起 --source stdin）" % args.reply_timeout, flush=True)
        return reply

    print("BOARD_CMD " + BOARD_CMD.format(x=point["x_mm"], y=point["y_mm"]), flush=True)
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stable-s", type=float, default=0.5, help="稳定窗口（秒）")
    parser.add_argument("--tol-mm", type=float, default=2.0, help="稳定判据的极差上限")
    parser.add_argument("--timeout", type=float, default=6.0, help="单次取点超时")
    parser.add_argument("--once", action="store_true", help="只抓一次就退出")
    parser.add_argument("--json", action="store_true", help="只输出一行 JSON")
    parser.add_argument("--log", type=Path, help="追加一行 JSONL（证据留痕）")
    sub = parser.add_mutually_exclusive_group()
    sub.add_argument("--udp", metavar="HOST:PORT", help="发给板端 UDP 服务")
    sub.add_argument("--serial", metavar="COMx", help="发给板端串口（板端 --source stdin）")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--reply-timeout", type=float, default=60.0,
                        help="等板端回包的秒数（一轮抓取约 8 s）")
    parser.add_argument("--camera-index", type=int, default=gp.DEFAULT_CAMERA_INDEX)
    parser.add_argument("--backend", choices=("dshow", "msmf", "any"), default="dshow")
    parser.add_argument("--calibration", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", choices=("auto", "cpu", "0"), default="auto")
    parser.add_argument("--class-name", choices=tuple(gp.CLASS_FILTER), default="any")
    parser.add_argument("--exposure", type=int)
    parser.add_argument("--auto-exposure", action="store_true")
    args = parser.parse_args(argv)

    args.transport = "udp" if args.udp else ("serial" if args.serial else "stdout")
    if args.stable_s <= 0 or args.tol_mm <= 0 or args.timeout <= 0:
        parser.error("--stable-s / --tol-mm / --timeout 必须 > 0")
    if args.udp:
        host, _, port = args.udp.rpartition(":")
        if not host or not port.isdigit():
            parser.error("--udp 要写成 HOST:PORT，例如 10.83.133.9:5005")

    try:
        calibration, detector, camera = open_stack(args)
    except (OSError, ValueError, RuntimeError, FileNotFoundError) as error:
        print("CAPTURE_FAIL stage=init %s" % error, file=sys.stderr)
        return 3

    sampler = Sampler(calibration, args.stable_s, args.tol_mm)
    exit_code = 0
    try:
        if args.once:
            exit_code = one_shot(args, calibration, detector, camera, sampler)
        else:
            print("就绪：输入 static capture 取点并抓取，q 退出", flush=True)
            while True:
                try:
                    line = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line:
                    continue
                if line.lower() in ("q", "quit", "exit"):
                    break
                if line.lower() not in TRIGGERS:
                    print("只认 %s" % " / ".join(TRIGGERS), flush=True)
                    continue
                sampler.samples.clear()
                one_shot(args, calibration, detector, camera, sampler)
    finally:
        camera.close()
    return exit_code


def one_shot(args, calibration, detector, camera, sampler) -> int:
    point = do_capture(args, calibration, detector, camera, sampler)
    if point is None:
        return 4

    packet = {"cmd": "static_capture", "trigger": "static capture",
              "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), **point,
              "source": "capture_agent/%s" % args.transport}
    reply = send(args, packet, point)
    record = dict(packet)
    if reply is not None:
        record["reply"] = reply
        print("CAPTURE_REPLY ok=%s grip=%s cycle_ms=%s grip_pos=%s fault=%s"
              % (reply.get("ok"), reply.get("grip"), reply.get("cycle_ms"),
                 reply.get("gripper_position"), reply.get("fault")), flush=True)
    print("CAPTURE_POINT x_mm=%.2f y_mm=%.2f stable=%.2fs n=%d spread=%.2f/%.2fmm conf=%.2f"
          % (point["x_mm"], point["y_mm"], point["stable_s"], point["n"],
             point["spread_mm"][0], point["spread_mm"][1], point["conf"]), flush=True)

    if args.log:
        try:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            with args.log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as error:
            print("CAPTURE_WARN log_failed %s" % error, file=sys.stderr)
    if args.json:
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return 0 if (reply is None or reply.get("ok")) else 5


if __name__ == "__main__":
    sys.exit(main())
