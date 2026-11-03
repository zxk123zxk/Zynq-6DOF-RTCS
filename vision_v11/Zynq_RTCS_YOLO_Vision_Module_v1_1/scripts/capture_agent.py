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

**类别分流（2026-10-27 定）**：`--class-name cube` 时只抓 Cube，检出 Cylinder 一律
**放行不抓**，并打印 `CAPTURE_PASS action=pass class=Cylinder`。放行是一条明确结论
（看见了、认出来了、按规则不抓），不是"没看见"——演示与证据要能区分这两件事。
默认 `--class-name any` 保持旧行为（取置信度最高者，不分类别）。

用法：
    .\\env.cmd scripts\\capture_agent.py
    .\\env.cmd scripts\\capture_agent.py --udp 10.83.133.9:5005
    .\\env.cmd scripts\\capture_agent.py --once --json
    .\\env.cmd scripts\\capture_agent.py --class-name cube --serial COM8

**默认是常驻模式（2026-10-29 改，10-31 修多件）**：不需要手敲 `static capture`，
检测到稳定目标就抓，抓完立刻按 x 从大到小抓下一件，一直跑，**按 q 退出**。
`--once` 才是跑一次就退。带上有几件就抓几件（按位置去重，不要求场景清空）；
越出示教区间（`--min-x/--max-x`）的件不抓，只打一行 `CAPTURE_SKIP reason=out_of_range`。
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
import keywatch
from vision.detector import DEFAULT_MODEL, Detector
from vision.plane_calibration import DEFAULT_PATH, PlaneCalibration

# 连续多少帧"只有不抓的那一类"就当场判放行（不吃满 --timeout）。
# 按 13/13 实测的 6 帧/0.5 s 算，4 帧≈0.33 s，圆柱在带上还能看清它就下结论。
VETO_FRAMES = 4
# 板端示教表的正本：抓取区间的上下沿由它决定，不另填常数（填了就会和表漂移）。
ROOT = Path(__file__).resolve().parents[3]
TEACHING_TABLE = ROOT / "config" / "grasp_teaching_table.json"
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


def classify_veto(result, cls: int | None, calibration,
                  min_conf: float = 0.0) -> object | None:
    """本次检测里"看见了、但按类别规则不抓"的目标（取带面内置信度最高的那个）。

    10-27 定：Cube 抓、Cylinder 放行。放行必须是**一条明确的结论**，不能等同于"没看见"
    ——否则演示时观众分不清"认出了圆柱故意不抓"和"系统根本瞎了"。
    只统计落在标定带面内的，避免把夹爪/背景误检当成"认出了一个圆柱"。
    """
    if cls is None:
        return None
    for item in sorted(result.detections, key=lambda d: d.confidence, reverse=True):
        if item.confidence < min_conf:
            continue
        if item.class_id != cls and gp.inside_belt(calibration, item.center_x, item.center_y):
            return item
    return None


def _report_multi(result, cls, calibration, min_conf: float) -> bool:
    """带面内≥2 个合规目标时打一行候选清单（每轮只打一次）。

    多件时"只抓一件、其余不动"这类问题，光看结果日志是查不出来的：必须知道当帧到底
    看见了几个、各自 x 是多少、最后选了哪个。返回 True 表示已报过。
    """
    items = [d for d in result.detections if cls is None or d.class_id == cls]
    items = [d for d in items
             if d.confidence >= min_conf
             and gp.inside_belt(calibration, d.center_x, d.center_y)]
    if len(items) < 2:
        return False
    items.sort(key=lambda d: calibration.to_mm(d.center_x, d.center_y)[0], reverse=True)
    print("CAPTURE_MULTI n=%d 候选 x=%s → 选 x 最大那件"
          % (len(items),
             " ".join("%.0f(%.2f)" % (calibration.to_mm(d.center_x, d.center_y)[0],
                                      d.confidence) for d in items[:6])), flush=True)
    return True


def do_capture(args, calibration, detector, camera, sampler: Sampler,
               quiet: bool = False, timeout: float | None = None,
               exclude: "list[float] | None" = None,
               blocked: "list[float] | None" = None):
    """抓一次点。

    返回点 dict；被类别规则放行返回 {"skip": True, ...}；超时返回 None。
    ``quiet=True``（常驻模式）时，整段时间什么都没看见就不打 CAPTURE_FAIL——
    带子空着本来就不该刷错误，否则日志会被"失败"淹没。
    ``timeout`` 覆盖 ``--timeout``：常驻模式用短窗口轮询，新放上去的件能更快被发现。
    ``exclude``：已经抓过/被判不可抓的 x（mm），选目标时先剔掉——**必须在选之前剔**，
    否则带上有两件时，已抓那件位置上常驻的"夹爪误检"会被每帧选成第一，第二件永远轮不到。
    ``blocked``：本次新判定为"不可抓"（越出示教区间、置信度过低）的位置，由调用方带时间戳
    收进 ``exclude``；不返回的话下一轮又会选中同一件，把后面可抓的件堵住。
    """
    cls = gp.CLASS_FILTER[args.class_name]
    window_s = args.timeout if timeout is None else timeout
    started = time.monotonic()
    deadline = started + window_s
    attempts, frames, no_target, off_belt, out_range = 0, 0, 0, 0, 0
    # 被类别规则挡下的帧计数（按类名分开记，便于日志里说清"放行的是圆柱"）
    vetoed: dict[str, int] = {}
    veto_conf = 0.0
    skipped = [float(x) for x in (exclude or ())]
    multi_reported = False
    print("CAPTURE_START stable=%.2fs tol=%.1fmm timeout=%.1fs only=%s range=%.0f..%.0f"
          % (args.stable_s, args.tol_mm, window_s, args.class_name,
             args.min_x, args.max_x), flush=True)

    while time.monotonic() < deadline:
        frame = camera.read()
        frames += 1
        now = time.monotonic()
        try:
            result = detector.detect(frame)
        except ValueError as error:
            print("CAPTURE_WARN detect_skipped %s" % error, file=sys.stderr, flush=True)
            continue
        if not multi_reported:
            multi_reported = _report_multi(result, cls, calibration, args.min_conf)
        target, n_all, margin = gp.pick_target(result, cls, calibration,
                                               exclude_x=skipped,
                                               exclude_mm=args.dup_mm,
                                               min_conf=args.min_conf)
        if target is None:
            no_target += 1
            veto = classify_veto(result, cls, calibration, args.min_conf)
            if veto is not None:
                vetoed[veto.class_name] = vetoed.get(veto.class_name, 0) + 1
                veto_conf = max(veto_conf, veto.confidence)
                if attempts == 0 and vetoed[veto.class_name] >= VETO_FRAMES:
                    # 连续 VETO_FRAMES 帧只看见"不抓的那一类"、且从没出现过合法目标
                    # → 当场判放行。等满 --timeout 的话，演示时圆柱早走出画面了。
                    return _pass_result(vetoed, veto_conf, frames)
            sampler.drop_if_lost(now)
            continue
        x_mm, y_mm = calibration.to_mm(target.center_x, target.center_y)
        if not gp.inside_belt(calibration, target.center_x, target.center_y):
            # 中心落在标定带面外的检测不是工件。10-25 记过吸顶灯被当成 Cube
            # （conf 0.30~0.36）；10-27 又实测到 y=150 mm 的假目标（带面只到 80 mm），
            # conf 0.26 却照样出点。这类点喂给 --grasp-xy 会被插值两端夹住、
            # "变成任意的合法姿态"，臂就去抓空气——比不出点更糟。
            # 所以不采用；但只计数+告警，计时器照常走完，结论仍由超时给出。
            off_belt += 1
            sampler.drop_if_lost(now)
            continue
        if not args.min_x <= x_mm <= args.max_x:
            # 2026-10-31 加：**越出示教区间不抓**。插值两端是"夹住不外推"，
            # 落在 290 左边会被当成 295 的姿态、落在 420 右边会被当成 420 的姿态，
            # 结果臂照跑一轮、抓的是空气（更糟：可能撞到带外的结构件）。
            out_range += 1
            skipped.append(x_mm)
            if blocked is not None:
                blocked.append(x_mm)
            if out_range == 1:
                print("CAPTURE_SKIP reason=out_of_range x=%.1f 不在示教区间 %.0f..%.0f"
                      "（夹住不外推，这一件不抓）" % (x_mm, args.min_x, args.max_x),
                      flush=True)
            sampler.drop_if_lost(now)
            continue
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

    if vetoed and attempts == 0:
        return _pass_result(vetoed, veto_conf, frames)
    if not (quiet and attempts == 0):
        print("CAPTURE_FAIL reason=timeout frames=%d no_target=%d off_belt=%d "
              "out_range=%d samples=%d"
              % (frames, no_target, off_belt, out_range, len(sampler.samples)), flush=True)
    if out_range and not quiet:
        print("CAPTURE_WARN 有 %d 帧的目标越出示教区间 %.0f..%.0f（没抓；要抓请补教点）"
              % (out_range, args.min_x, args.max_x), flush=True)
    if off_belt and not quiet:
        print("CAPTURE_WARN 有 %d 帧的检测中心落在标定带面外（判为背景误检，已丢弃）"
              % off_belt, flush=True)
    if sampler.samples:
        xs = [s[1] for s in sampler.samples]
        ys = [s[2] for s in sampler.samples]
        print("CAPTURE_WARN 最近一段的极差 x=%.1f y=%.1f mm（阈值 %.1f）：目标在动，或框在跳"
              % (max(xs) - min(xs), max(ys) - min(ys), args.tol_mm), flush=True)
    return None


def _pass_result(vetoed: dict[str, int], veto_conf: float, frames: int) -> dict:
    """按类别规则放行的结果。不是失败：什么都不发、不产生运动。"""
    name = max(vetoed, key=lambda key: vetoed[key])
    print("CAPTURE_PASS action=pass class=%s conf=%.2f frames=%d hits=%d "
          "（只抓 cube，这一类按规则放行）"
          % (name, veto_conf, frames, vetoed[name]), flush=True)
    return {"skip": True, "class_name": name, "conf": round(veto_conf, 3),
            "hits": vetoed[name], "frames": frames}


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
        shell_ate_it = False
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
                # 板端没有 server 占住这条控制台时，我们发的这行 JSON 会被 shell 当成命令
                # 执行，回显里必然出现 "command not found"，随后弹回 "#" 提示符。
                # 这时等满 --reply-timeout 毫无意义，立刻收尾并把该做什么说清楚。
                if "command not found" in text or text.endswith("#"):
                    shell_ate_it = True
                    break
        if lines:
            print("BOARD_LOG 前 %d 行板端输出：" % min(len(lines), 14), flush=True)
            for text in lines[:14]:
                print("  " + text[:160], flush=True)
        if reply is None and shell_ate_it:
            print("CAPTURE_FAIL 板端没有 server 在占住控制台：这行 JSON 被 shell 当命令执行了。"
                  "先在那条串口控制台上跑 "
                  "sudo python3 scripts/static_grasp_server.py --source stdin，"
                  "看到 SERVER_READY 再重发（坐标已打印，可人工兜底）", flush=True)
            return None
        if reply is None:
            print("CAPTURE_FAIL 串口 %.0fs 内没等到 REPLY（板端 server 在跑吗？"
                  "起 --source stdin）" % args.reply_timeout, flush=True)
        return reply

    print("BOARD_CMD " + BOARD_CMD.format(x=point["x_mm"], y=point["y_mm"]), flush=True)
    return None


def taught_range() -> tuple[float, float]:
    """示教表覆盖的 x 区间（抓取区间的唯一来源）。读不到就退回 295..420 并告警。

    为什么取表的实际两端而不是写死 290/420：插值两端是"夹住不外推"，表外 5 mm 的
    物块轨迹仍然等于端点姿态；到底算不算"能抓"必须由表的覆盖范围说话。
    """
    try:
        raw = json.loads(TEACHING_TABLE.read_text(encoding="utf-8"))
        xs = [float(point["x_mm"]) for point in raw]
        return min(xs), max(xs)
    except (OSError, ValueError, KeyError, TypeError):
        print("CAPTURE_WARN 读不到示教表 %s，抓取区间退回 295..420（可用 --min-x/--max-x 覆盖）"
              % TEACHING_TABLE, file=sys.stderr, flush=True)
        return 295.0, 420.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stable-s", type=float, default=0.5, help="稳定窗口（秒）")
    parser.add_argument("--tol-mm", type=float, default=2.0, help="稳定判据的极差上限")
    parser.add_argument("--timeout", type=float, default=6.0, help="单次取点超时")
    parser.add_argument("--auto-timeout", type=float, default=2.0,
                        help="常驻模式每次轮询的窗口（秒）。短一点，新放上去的件能更快被发现")
    parser.add_argument("--dup-mm", type=float, default=8.0,
                        help="防重抓：和上次下发的位置相差不到这么多 mm 就当作同一件")
    parser.add_argument("--retry-after-s", type=float, default=3.0,
                        help="防重抓：同一位置在这么多秒内不重复下发（夹空后重试要等）")
    taught_lo, taught_hi = taught_range()
    parser.add_argument("--min-x", type=float, default=taught_lo,
                        help="可抓区间的下沿（mm），默认取示教表最小 x = %.1f" % taught_lo)
    parser.add_argument("--max-x", type=float, default=taught_hi,
                        help="可抓区间的上沿（mm），默认取示教表最大 x = %.1f" % taught_hi)
    parser.add_argument("--min-conf", type=float, default=0.45,
                        help="候选目标的置信度门槛。夹爪误检 0.26~0.43、真方块 0.74~0.87，"
                             "0.45 把夹爪/背景挡在外面；真方块偏暗时可下调")
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
    if args.min_x >= args.max_x:
        parser.error("--min-x 必须小于 --max-x（当前 %.1f..%.1f）" % (args.min_x, args.max_x))
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
            exit_code = auto_loop(args, calibration, detector, camera, sampler)
    finally:
        camera.close()
    return exit_code


def auto_loop(args, calibration, detector, camera, sampler) -> int:
    """常驻模式：一直跑，抓完立刻按 x 从大到小抓下一件，按 q 退出。

    四条纪律：
      1. 发命令之后到回执之前**不做检测**——板端一动夹爪就进画面（还会被误检成 Cube）；
      2. 回执之后**立刻重新武装**，不要求场景清空：传送带上常常还有别的件，
         要求"清空"只会白等（10-29 踩过，死等 20 s）；
      3. 防重抓靠**位置去重**，不靠场景清空：同一位置（±dup_mm）刚试过，
         `--retry-after-s` 秒内不再重复下发；不同位置（多件）则立刻抓下一件。
         去重是在 `pick_target` **选之前**剔掉的（10-31 改）：选完再否掉会让第二件
         永远轮不到——已抓那件的位置上常驻着被误检成 Cube 的夹爪，它 x 更大。
      4. 越出示教区间（`--min-x/--max-x`，默认取示教表两端）**不抓**，并把这个位置
         记为已处理，免得它一直当"最大 x"把别的件堵住。
    """
    print("CAPTURE_READY 常驻模式：按 x 从大到小依次抓，按 q 退出", flush=True)
    recent: list[tuple[float, float]] = []      # (x_mm, 时间)：已下发或已判不可抓的位置
    index = 0
    while True:
        if "q" in keywatch.poll():
            print("CAPTURE_INFO 按 q 退出", flush=True)
            return 0
        now = time.monotonic()
        recent = [item for item in recent if now - item[1] <= args.retry_after_s]
        blocked: list[float] = []
        sampler.samples.clear()
        index += 1
        print("CAPTURE_CYCLE start=%d" % index, flush=True)
        point = do_capture(args, calibration, detector, camera, sampler, quiet=True,
                           timeout=args.auto_timeout,
                           exclude=[x for x, _t in recent], blocked=blocked)
        if blocked:
            stamp = time.monotonic()
            recent.extend((x, stamp) for x in blocked)
        if point is None or point.get("skip"):
            continue
        if any(abs(point["x_mm"] - x) <= args.dup_mm for x, _t in recent):
            # 同一件还在原地（上一次夹空）：等 `--retry-after-s` 之后再试，不重复下发。
            time.sleep(0.2)
            continue
        deliver(args, point)
        recent.append((point["x_mm"], time.monotonic()))


def one_shot(args, calibration, detector, camera, sampler) -> int:
    """取一次点并按结果分发（--once 和手动敲命令都走这里）。"""
    point = do_capture(args, calibration, detector, camera, sampler)
    if point is None:
        return 4
    return deliver(args, point)


def deliver(args, point: dict) -> int:
    """把一个已确定的点送出去并记录；放行分支也在这里。"""
    if point.get("skip"):
        # 放行：不发串口、不产生运动帧。按规则这是正常结果（退出码 0），
        # 但必须留一行可统计的记录——演示与证据里要能说"这一次是认出了圆柱才放走的"。
        record = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "action": "pass", "class_name": point["class_name"],
                  "conf": point["conf"], "hits": point["hits"],
                  "frames": point["frames"], "class_filter": args.class_name,
                  "source": "capture_agent/%s" % args.transport}
        if args.log:
            try:
                args.log.parent.mkdir(parents=True, exist_ok=True)
                with args.log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as error:
                print("CAPTURE_WARN log_failed %s" % error, file=sys.stderr)
        if args.json:
            print(json.dumps(record, ensure_ascii=False), flush=True)
        return 0

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
