"""动态抓取（G5）：越线触发 + 定时闭爪。

每个循环五步：

    ARM    等物块：黄框（标定带面）内、类别合规、且**还在拦截窗口上游**
    TRIG   物块越检测线的那一帧 → 算 x_int / t_block / t_close / t_stage
    STAGE  到 t_stage 才发 dynamic_stage（臂从 exit 高位扑向 x_int，约 1.95 s）
    CLOSE  到 t_close 发 dynamic_close → 板端闭爪 + lift/place/retreat/exit
    RECORD 带速 / 检测线 / 拦截点 / T_flight / 预测偏差 / grip / 周期

**这是"静态抓取的动态版"**：臂不提前守在拦截点，而是踩着点从高位过去，到位后几乎
立刻闭爪——和静态抓取一样"先到物块所在处再闭爪"，所以 x 由插值给出、姿态与静态完全
一致；不同的只是"什么时候出发"由实测带速算出来（2026-10-29 按用户要求改）。

**时刻怎么算**（见 docs/5.G5）：

    x_int   = 物块当前位置 + v×(advance + move + margin)     ，夹在窗口 [350,390] 内
    t_block = 物块中心到达 x_int 的时刻
    t_close = t_block − advance          （爪在物块到点时正好咬上）
    t_stage = t_close − move − margin    （臂到位的时刻）

**多个目标**：黄框内取 x 最大的那件（下游优先）——它最先到拦截点。规则的具体实现
在 `grasp_point.pick_target`，本脚本按同一规则、但只在"拦截窗口上游"的候选里选。

不连板也能验时序：`--dry-run` 只算不发，打印 `WOULD_STAGE` / `WOULD_CLOSE`。
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grasp_point as gp
import keywatch
from vision.detector import DEFAULT_MODEL, Detector
from vision.plane_calibration import DEFAULT_PATH, PlaneCalibration

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "g5_dynamic.json"
RUNS_ROOT = ROOT / "vision_runs"
# 物块至少连续这么多帧出现在检测线上游，才认为"这一次是真的要抓它"。
# 防的是上一轮遗留的物块、或背景误检在拦截点附近冒充目标。
ARM_FRAMES = 3
# 拟合带速时保留多少帧（95 ms/帧 → 12 帧约 1.1 s，够压掉单帧抖动）
TRACK_SAMPLES = 12
# 键盘按 q 之后，正在等越线/等时刻的循环要在下一帧或下一次检查时退出。
_STOP = False


def poll_keys() -> None:
    """把 q 记成停止请求；其它键忽略（以后要加"立即抓"再扩展）。"""
    global _STOP
    if "q" in keywatch.poll():
        _STOP = True
        print("G5_INFO 收到 q：本循环结束后退出", flush=True)


@dataclass(frozen=True)
class Plan:
    """一次开机内不变的常数：几何 + 带速 + 两个实测时间。"""
    speed_mm_s: float
    direction: int              # +1 = 物块沿 +x 走；-1 = 沿 -x 走
    x_line_mm: float
    x_intercept_mm: float       # 只在 --x-intercept 强制固定点时使用
    force_intercept: bool
    window_mm: tuple[float, float]   # 允许的拦截点区间（默认 350–390）
    advance_s: float            # 发闭爪命令 → 爪接触物块（约 0.7 s）
    move_s: float               # 发 dynamic_stage → 臂到位（实测 1.95 s）
    stage_margin_s: float       # 到位后再留一点让臂停稳
    min_upstream_mm: float
    grip_y_mm: float
    grip_target: int
    grip_speed: int
    grip_observe_ms: int
    id2_offset: int

    def choose_intercept(self, x_mm: float, speed_mm_s: float | None = None) -> float:
        """在窗口里挑一个"现在出发正好赶上"的拦截点。

        need = 物块当前位置 + 带速×(闭爪提前量 + 到位时间 + 停稳余量)。
        比这更远的拦截点就来不及了，所以从 need 起在窗口内取——**每次都不同，
        插值才真正起作用**（写死 370 的话 x 这一维等于没用）。
        """
        if self.force_intercept:
            return self.x_intercept_mm
        speed = self.speed_mm_s if speed_mm_s is None else speed_mm_s
        need = x_mm + self.direction * speed * (
            self.advance_s + self.move_s + self.stage_margin_s)
        lo, hi = min(self.window_mm), max(self.window_mm)
        return min(max(need, lo), hi)

    def schedule(self, t_frame: float, x_mm: float, speed_mm_s: float | None = None):
        """返回 (x_int, t_block, t_close, t_stage)。

        t_block —— 物块中心到达 x_int 的时刻
        t_close —— 该发闭爪命令的时刻（提前 advance，爪正好在物块到点时咬上）
        t_stage —— 该发 dynamic_stage 的时刻（再提前"到位时间 + 停稳余量"）

        ``speed_mm_s`` 传当轮实测的带速（视野里拟合出来的），不传就用配置值。
        这就是"静态抓取的动态版"：臂不提前守在那儿，而是踩着点从 exit 高位扑过去，
        到位后几乎立刻闭爪。
        """
        speed = self.speed_mm_s if speed_mm_s is None else speed_mm_s
        x_int = self.choose_intercept(x_mm, speed)
        t_block = t_frame + (x_int - x_mm) * self.direction / speed
        t_close = t_block - self.advance_s
        t_stage = t_close - self.move_s - self.stage_margin_s
        return x_int, t_block, t_close, t_stage

    def upstream_of_line(self, x_mm: float) -> bool:
        return (x_mm - self.x_line_mm) * self.direction < 0

    def eligible(self, x_mm: float) -> bool:
        """物块离"窗口靠近自己的那一端"还有 min_upstream_mm 以上。

        来不来得及由 schedule() 的 t_stage 判定并告警，这里只挡掉窗口边上的。
        """
        if self.force_intercept:
            near = self.x_intercept_mm
        else:
            lo, hi = min(self.window_mm), max(self.window_mm)
            near = lo if self.direction > 0 else hi
        return (near - x_mm) * self.direction >= self.min_upstream_mm


def load_plan(args) -> Plan:
    """配置 + 命令行覆盖；速度没测就拒绝（不是门禁，是没法除）。"""
    data = {}
    if args.config.exists():
        try:
            data = json.loads(args.config.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            print("G5_WARN config_unreadable %s（用命令行参数继续）" % error, file=sys.stderr)
    belt = data.get("belt", {})
    geometry = data.get("geometry", {})
    timing = data.get("timing", {})

    speed = args.speed if args.speed is not None else belt.get("speed_mm_s")
    if not isinstance(speed, (int, float)) or speed <= 0:
        print("G5_FAIL 带速没有实测值：先跑\n"
              "  .\\env.cmd scripts\\g5_belt_profile.py --seconds 6 --write-config\n"
              "或临时用 --speed 40 给一个值", file=sys.stderr)
        raise SystemExit(2)

    direction = args.direction or belt.get("direction", "+x")
    window = geometry.get("intercept_window_mm", [350.0, 390.0])
    if not isinstance(window, (list, tuple)) or len(window) != 2:
        window = [350.0, 390.0]
    grip = timing.get("grip_close", {}) if isinstance(timing.get("grip_close"), dict) else {}
    return Plan(
        speed_mm_s=float(speed),
        direction=-1 if direction == "-x" else 1,
        x_line_mm=float(args.x_line if args.x_line is not None
                        else geometry.get("detection_line_x_mm", 120.0)),
        x_intercept_mm=float(args.x_intercept if args.x_intercept is not None
                             else geometry.get("intercept_x_mm", 370.0)),
        force_intercept=args.x_intercept is not None,
        window_mm=(float(window[0]), float(window[1])),
        advance_s=float((args.advance_ms if args.advance_ms is not None
                         else timing.get("advance_ms", 700)) / 1000.0),
        move_s=float(timing.get("move_to_pose_ms", 1950)) / 1000.0,
        stage_margin_s=float(timing.get("stage_margin_ms", 150)) / 1000.0,
        min_upstream_mm=float(geometry.get("min_upstream_mm", 30.0)),
        grip_y_mm=float(args.grip_y),
        grip_target=int(grip.get("target", 2200)),
        grip_speed=int(args.grip_speed if args.grip_speed is not None
                       else grip.get("speed", 1500)),
        grip_observe_ms=int(args.grip_observe_ms if args.grip_observe_ms is not None
                            else grip.get("observe_ms", 1000)),
        id2_offset=int(args.id2_offset if args.id2_offset is not None
                       else geometry.get("intercept_id2_offset", 0)),
    )


class Link:
    """与板端的一条命令通道。串口**全程持有**，不在每条命令上开关一次。

    开关串口会重新断言 DTR，部分 USB-UART 会因此给板子一个边沿；更要紧的是开端口
    本身有几十毫秒，正好落在"提前量"的关键路径上。所以只在启动时开一次。
    """

    def __init__(self, args):
        self.kind = "udp" if args.udp else ("serial" if args.serial else "stdout")
        self.args = args
        self.port = None
        self.sock = None
        if self.kind == "serial":
            import serial            # 只有真用串口时才要求 pyserial
            self.port = serial.Serial(args.serial, args.baud, timeout=0.5)
        elif self.kind == "udp":
            host, _, port = args.udp.rpartition(":")
            self.addr = (host, int(port))
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(0.5)

    def close(self) -> None:
        if self.port is not None:
            self.port.close()
        if self.sock is not None:
            self.sock.close()

    def send(self, packet: dict, expect: str, timeout_s: float):
        """发一条命令并等回包；回包必须带同名 cmd，免得把上一条的回包当成本条的。"""
        line = json.dumps(packet, ensure_ascii=False)
        if self.kind == "stdout":
            print("BOARD_CMD %s" % line, flush=True)
            return None
        if self.kind == "udp":
            return self._send_udp(line, expect, timeout_s)
        return self._send_serial(line, expect, timeout_s)

    def _send_serial(self, line: str, expect: str, timeout_s: float):
        self.port.write((line + "\n").encode("utf-8"))
        self.port.flush()
        deadline = time.monotonic() + timeout_s
        ignored: list[str] = []
        while time.monotonic() < deadline:
            raw = self.port.readline()
            if not raw:
                continue
            text = raw.decode("utf-8", "replace").strip()
            if not text:
                continue
            candidate = text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""
            if candidate:
                try:
                    parsed = json.loads(candidate)
                except ValueError:
                    parsed = None
                # **必须同时满足两条**才认作板端回包：
                #   cmd 同名   —— 区分上一条命令的回包
                #   有 ok 字段 —— 排除控制台回显。板端会把我们发进去的那行原样回显，
                #                回显里同样带 "cmd": "dynamic_stage"，只按 cmd 匹配会把
                #                回显当回包，于是 10 ms 就"返回"、ok=False，而板端的臂
                #                其实还在动（2026-10-29 实际踩到）。
                if isinstance(parsed, dict) and parsed.get("cmd") == expect \
                        and "ok" in parsed:
                    return parsed
            ignored.append(text)
            if "command not found" in text:
                # 板端没有 server 占住控制台：这行被 shell 吃掉了，再等没意义。
                print("G5_FAIL 板端没有 server 在占控制台（回显 %r）。先跑 "
                      "sudo python3 scripts/static_grasp_server.py --source stdin"
                      % text[:80], file=sys.stderr)
                return None
        for text in ignored[:6]:
            print("  BOARD %s" % text[:150], flush=True)
        return None

    def _send_udp(self, line: str, expect: str, timeout_s: float):
        self.sock.sendto(line.encode("utf-8"), self.addr)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                data, _peer = self.sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            try:
                parsed = json.loads(data.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(parsed, dict) and parsed.get("cmd") == expect:
                return parsed
        return None


def sleep_until(target: float) -> None:
    """睡到指定单调时刻。最后 3 ms 自旋，避开 Windows 定时器 15 ms 的粒度。"""
    while True:
        remaining = target - time.monotonic()
        if remaining <= 0:
            return
        if remaining > 0.003:
            time.sleep(remaining - 0.003)
        else:
            while time.monotonic() < target:
                pass


def estimate_speed(history: list[tuple[float, float]], min_span_s: float = 0.3,
                   min_samples: int = 4) -> float | None:
    """用视野里的 x(t) 估带速（mm/s，带符号）；样本不够或不像直线就返回 None。

    为什么在循环里现估：配置里的带速是开机时量一次，档位一动、带子一热、载荷一变就
    不一样了。而物块从检测线走到拦截点有 2~3 s、二十几帧，**白白浪费这段观测**太可惜。
    拟合出来的速度直接进 `x_int / t_block`，比用常数更准。

    只用最小二乘，不做鲁棒回归：跨度 ≥0.3 s、样本 ≥4，且斜率落在 10~300 mm/s。
    不满足就返回 None，调用方退回配置值（并打一行说明）。
    """
    if len(history) < min_samples:
        return None
    span = history[-1][0] - history[0][0]
    if span < min_span_s:
        return None
    base = history[0][0]
    times = [item[0] - base for item in history]
    xs = [item[1] for item in history]
    n = len(times)
    mean_t = sum(times) / n
    mean_x = sum(xs) / n
    den = sum((t - mean_t) ** 2 for t in times)
    if den <= 0:
        return None
    slope = sum((t - mean_t) * (x - mean_x) for t, x in zip(times, xs)) / den
    if not 10.0 <= abs(slope) <= 300.0:
        return None
    return slope


def wait_for_crossing(args, calibration, detector, camera, plan: Plan, cls):
    """等物块越线；返回 (t_frame, x_mm, y_mm, conf, n_candidates) 或 None。

    候选规则：黄框内、类别合规、且还在拦截点上游 min_upstream_mm 以外。
    多个候选时取**最靠下游**的那个（+x 取最大、-x 取最小），它最先到拦截点。
    """
    deadline = time.monotonic() + args.watch_timeout
    upstream_hits = 0
    armed = False
    last_report = 0.0
    downstream_warned = False
    # 上游段的位置-时间序列，用来在越线那一刻拟合出真实带速（见 estimate_speed）。
    history: list[tuple[float, float]] = []
    while time.monotonic() < deadline:
        poll_keys()
        if _STOP:
            return None
        frame = camera.read()
        t_frame = time.monotonic()
        try:
            result = detector.detect(frame)
        except ValueError as error:
            print("G5_WARN detect_skipped %s" % error, file=sys.stderr)
            continue
        candidates = []
        for item in result.detections:
            if cls is not None and item.class_id != cls:
                continue
            if not gp.inside_belt(calibration, item.center_x, item.center_y):
                continue
            x_mm, y_mm = calibration.to_mm(item.center_x, item.center_y)
            if not plan.eligible(x_mm):
                continue
            candidates.append((x_mm, y_mm, item))
        if not candidates:
            continue
        x_mm, y_mm, target = max(candidates, key=lambda c: c[0] * plan.direction)

        if plan.upstream_of_line(x_mm):
            upstream_hits += 1
            # 按"沿运动方向的距离"存，估出来的斜率就恒为正，方向由 plan.direction 管。
            history.append((t_frame, x_mm * plan.direction))
            if len(history) > TRACK_SAMPLES:
                history.pop(0)
            if not armed and upstream_hits >= ARM_FRAMES:
                armed = True
                downstream_warned = False
                print("G5_ARMED x=%.1f conf=%.2f candidates=%d（连续 %d 帧在检测线上游，"
                      "从这里开始算提前量）"
                      % (x_mm, target.confidence, len(candidates), upstream_hits), flush=True)
            if armed:
                now = time.monotonic()
                if now - last_report > 0.5:
                    last_report = now
                    print("G5_ARM x=%.1f to_line=%.1fmm conf=%.2f"
                          % (x_mm, abs(plan.x_line_mm - x_mm), target.confidence), flush=True)
            continue

        # 已经在检测线下游：**这一步绝不能先清 armed**，否则越线的那一帧永远是
        # "从未武装"，一次也触发不了（2026-10-29 实际踩到，整轮 60 s 空等）。
        if armed:
            history.append((t_frame, x_mm * plan.direction))
            return (t_frame, x_mm, y_mm, target.confidence, len(candidates),
                    estimate_speed(history))

        upstream_hits = 0
        if not downstream_warned:
            downstream_warned = True
            print("G5_WARN 物块 x=%.1f 已在检测线 %.1f 下游，但之前没有连续 %d 帧在上游："
                  "本次不触发。把它放到上游（x%s%.0f）再开带"
                  % (x_mm, plan.x_line_mm, ARM_FRAMES,
                     "<" if plan.direction > 0 else ">", plan.x_line_mm), flush=True)
    return None


def one_cycle(args, calibration, detector, camera, link: Link, plan: Plan, cls,
              index: int, log_path: Path) -> dict:
    """跑一个完整循环：等越线 → 预测拦截点与时刻 → 踩着点出发 → 闭爪 → 记录。

    **默认不提前就位**：臂起始在 exit 高位（上一轮 `--resume close` 的落点），等物块
    越线后按 `t_stage` 才出发，到位后几乎立刻闭爪。这就是"静态抓取的动态版"——
    臂是"扑过去"而不是"守在那儿"，x 由插值给出、姿态与静态完全一致。
    """
    print("G5_CYCLE start=%d/%d v=%.1fmm/s line=%.0f window=%.0f..%.0f "
          "advance=%dms move=%dms"
          % (index, args.cycles, plan.speed_mm_s, plan.x_line_mm,
             min(plan.window_mm), max(plan.window_mm),
             round(plan.advance_s * 1000), round(plan.move_s * 1000)), flush=True)
    record = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "cycle": index,
              "speed_mm_s": plan.speed_mm_s, "direction": plan.direction,
              "x_line_mm": plan.x_line_mm, "advance_ms": round(plan.advance_s * 1000),
              "move_ms": round(plan.move_s * 1000), "class_filter": args.class_name}

    if args.pre_stage:
        # 旧行为（先守株待兔），留作 A/B 对照，不作为默认。
        if args.dry_run:
            print("G5_STAGE skipped reason=dry_run(--pre-stage)", flush=True)
        else:
            stage_sent = time.monotonic()
            reply = link.send({"cmd": "dynamic_stage", "x_mm": plan.x_intercept_mm,
                               "y_mm": plan.grip_y_mm,
                               "source": "g5_trigger/%s" % link.kind},
                              "dynamic_stage", args.reply_timeout)
            took_ms = int((time.monotonic() - stage_sent) * 1000)
            print("G5_STAGE pre ok=%s took_ms=%d（--pre-stage，先就位再等）"
                  % (bool(reply and reply.get("ok")), took_ms), flush=True)
            record["stage_ms"] = took_ms

    crossing = wait_for_crossing(args, calibration, detector, camera, plan, cls)
    if crossing is None:
        print("G5_FAIL reason=no_crossing 在 %.0fs 内没等到物块越线"
              % args.watch_timeout, flush=True)
        record["result"] = "no_crossing"
        append_jsonl(log_path, record)
        return record

    t_frame, x_mm, y_mm, conf, n_candidates, v_live = crossing
    v_used = plan.speed_mm_s if v_live is None else abs(v_live)
    if v_live is None:
        print("G5_INFO 视野里样本不够（<4 帧或跨度 <0.3 s），带速用配置值 %.1f"
              % plan.speed_mm_s, flush=True)
    elif abs(v_used - plan.speed_mm_s) / plan.speed_mm_s > 0.35:
        print("G5_WARN 视野实测带速 %.1f 与配置 %.1f 差 %.0f%%：档位变过，或被推着走"
              % (v_used, plan.speed_mm_s,
                 100 * abs(v_used - plan.speed_mm_s) / plan.speed_mm_s), flush=True)
    x_int, t_block, t_close, t_stage = plan.schedule(t_frame, x_mm, v_used)
    flight_s = (x_int - x_mm) * plan.direction / v_used
    now = time.monotonic()
    close_in_ms = (t_close - now) * 1000
    stage_in_ms = (t_stage - now) * 1000
    print("G5_TRIG x=%.1f y=%.1f conf=%.2f candidates=%d v=%.1f(配置 %.1f) -> "
          "x_int=%.0f T_flight=%.2fs close_in=%.0fms stage_in=%.0fms"
          % (x_mm, y_mm, conf, n_candidates, v_used, plan.speed_mm_s, x_int,
             flight_s, close_in_ms, stage_in_ms), flush=True)
    record.update({"x_trig_mm": round(x_mm, 2), "y_trig_mm": round(y_mm, 2),
                   "conf": round(conf, 3), "candidates": n_candidates,
                   "x_intercept_mm": round(x_int, 1),
                   "speed_used_mm_s": round(v_used, 2),
                   "speed_live_mm_s": None if v_live is None else round(abs(v_live), 2),
                   "t_flight_s": round(flight_s, 3),
                   "close_in_ms": round(close_in_ms),
                   "stage_in_ms": round(stage_in_ms)})
    if not plan.force_intercept:
        record["intercept_window_mm"] = [min(plan.window_mm), max(plan.window_mm)]
    if stage_in_ms < 0:
        print("G5_WARN 来不及（stage_in=%.0f ms）：物块进视野时已经离窗口太近。"
              "把检测线前移、或把窗口上移；这一轮会晚到、大概率夹空" % stage_in_ms,
              file=sys.stderr)

    if args.dry_run:
        print("WOULD_STAGE at %+.0f ms, WOULD_CLOSE at %+.0f ms "
              "(dry-run，不连板不发命令)" % (stage_in_ms, close_in_ms), flush=True)
        record["result"] = "dry_run"
        append_jsonl(log_path, record)
        return record

    if not args.pre_stage and not args.no_stage:
        sleep_until(max(t_stage, now))
        stage_sent = time.monotonic()
        reply = link.send({"cmd": "dynamic_stage", "x_mm": round(x_int, 2),
                           "y_mm": plan.grip_y_mm,
                           "id2_offset": plan.id2_offset,
                           "source": "g5_trigger/%s" % link.kind},
                          "dynamic_stage", args.reply_timeout)
        arrived_at = time.monotonic()
        took_ms = int((arrived_at - stage_sent) * 1000)
        ok = bool(reply and reply.get("ok"))
        record["stage_ms"] = took_ms
        print("G5_STAGE ok=%s took_ms=%d grip=%s x_int=%.1f"
              % (ok, took_ms, (reply or {}).get("grip"), x_int), flush=True)
        if not ok:
            # 臂没到位就别闭爪：闭了也只会夹空，而且这一趟的搬运/放置会从错的位姿起，
            # 把下一轮也带歪（2026-11-03 现场就是这样越跑越差的）。
            # 不是硬门禁：本轮记为 stage_failed 后**直接进入下一轮**，系统继续跑。
            print("G5_WARN stage 没成功：臂没到拦截位，本轮不闭爪、跳过（记 stage_failed）",
                  file=sys.stderr, flush=True)
            record["result"] = "stage_failed"
            append_jsonl(log_path, record)
            return record
        # **闭爪时刻取"到位"与 t_close 的晚者**，不是"到位就立刻闭"。
        #
        # 2026-11-03 实测教训：改了"到位即闭"之后，10 轮里 6 轮夹空，而夹空那 6 轮的
        # send_err 是 -454~+532 ms —— 臂到拦截位的耗时比计划早 250~460 ms（或晚 500 ms），
        # 闭爪时刻就整体跟着漂，物块要么还没进虎口、要么已经走过去。
        # 命中的 4 轮 send_err 全在 +7~+17 ms，正好是"按时刻闭"的结果。
        # 所以：早到就等到 t_close（这点等待是必需的，不是"愣神"）；晚到则立刻闭，不再拖。
        close_at = max(arrived_at, t_close)
        drift_ms = (arrived_at - t_close) * 1000
        record["stage_drift_ms"] = round(drift_ms)
        if drift_ms > 150:
            print("G5_WARN 臂到位比计划晚 %.0f ms：本次闭爪被迫推迟，move_to_pose_ms 应调大"
                  % drift_ms, flush=True)
        elif drift_ms < -150:
            print("G5_INFO 臂到位比计划早 %.0f ms：等满 t_close 再闭爪" % -drift_ms,
                  flush=True)
        sleep_until(close_at)
    else:
        # 臂已经在拦截位（--pre-stage / --no-stage）：这时才需要按时刻等。
        sleep_until(t_close)

    sent_at = time.monotonic()
    # 预测接触时刻的落点偏差：按 advance（命令→咬合 ≈0.3 s）推，不是按 0.5 s
    predicted = x_mm + plan.direction * v_used * (sent_at - t_frame + plan.advance_s)
    record["send_error_ms"] = round((sent_at - t_close) * 1000, 1)
    record["predicted_offset_mm"] = round(predicted - x_int, 1)

    cycle_started = time.monotonic()
    reply = link.send({"cmd": "dynamic_close", "x_mm": round(x_int, 2),
                       "y_mm": plan.grip_y_mm,
                       "grip": {"target": plan.grip_target, "speed": plan.grip_speed,
                                "observe_ms": plan.grip_observe_ms},
                       "source": "g5_trigger/%s" % link.kind},
                      "dynamic_close", args.reply_timeout)
    arm_ms = int((time.monotonic() - cycle_started) * 1000)
    record["arm_ms"] = arm_ms
    if reply is None:
        print("G5_FAIL reason=no_reply 闭爪命令没有回包", flush=True)
        record["result"] = "no_reply"
        append_jsonl(log_path, record)
        return record

    grip = reply.get("grip")
    position = reply.get("gripper_position")
    offset = record.get("predicted_offset_mm")
    print("G5_RESULT grip=%s grip_pos=%s close_ms=%s cycle_ms=%s arm_ms=%d "
          "send_err=%.1f ms pred_offset=%s mm"
          % (grip, position, reply.get("close_ms"), reply.get("cycle_ms"), arm_ms,
             record["send_error_ms"], offset), flush=True)
    record.update({"grip": grip, "gripper_position": position,
                   "cycle_ms": reply.get("cycle_ms"), "close_ms": reply.get("close_ms"),
                   "ok": reply.get("ok"), "fault": reply.get("fault"),
                   "result": "hit" if grip == "contact" else str(grip)})
    append_jsonl(log_path, record)
    return record


def append_jsonl(path: Path, record: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        print("G5_WARN log_failed %s" % error, file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cycles", type=int, default=1,
                        help="跑几轮（验收 5 次就给 5）；--loop 时忽略")
    parser.add_argument("--loop", action="store_true",
                        help="一直跑，直到按 q 或 Ctrl-C（默认只跑 --cycles 轮）")
    parser.add_argument("--grip-speed", type=int,
                        help="闭爪速度（raw，上限 1500）。默认取配置，10-29 起为 1500")
    parser.add_argument("--grip-observe-ms", type=int,
                        help="闭爪后的观测窗口（ms）。默认取配置，1000（C 命令行下限）")
    parser.add_argument("--id2-offset", type=int,
                        help="拦截位 ID2 的偏移（负值=抬高夹取点）。默认取配置，0")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--class-name", choices=tuple(gp.CLASS_FILTER), default="cube",
                        help="只抓哪一类；默认 cube（圆柱放行）")
    parser.add_argument("--speed", type=float, help="覆盖配置里的带速（mm/s）")
    parser.add_argument("--direction", choices=("+x", "-x"), help="覆盖配置里的方向")
    parser.add_argument("--x-line", type=float, help="覆盖检测线 x（mm）")
    parser.add_argument("--x-intercept", type=float,
                        help="强制固定拦截点（关闭 350–390 窗口，回到'守株待兔'的选点方式）")
    parser.add_argument("--grip-y", type=float, default=36.0,
                        help="送坐标用的 y（示教表只有 y=36 一条车道）")
    parser.add_argument("--advance-ms", type=float,
                        help="覆盖提前量（默认取配置，700 ms）")
    parser.add_argument("--pre-stage", action="store_true",
                        help="回到旧行为：先就位再等（A/B 对照用）。默认是越线后踩着点出发")
    parser.add_argument("--no-stage", action="store_true",
                        help="完全不发 dynamic_stage（臂已在拦截位时用）")
    parser.add_argument("--watch-timeout", type=float, default=60.0,
                        help="等物块越线的超时（秒）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只算时序、不发命令（不连板验算法用）")
    parser.add_argument("--log", type=Path, help="试验记录 JSONL")
    sub = parser.add_mutually_exclusive_group()
    sub.add_argument("--udp", metavar="HOST:PORT")
    sub.add_argument("--serial", metavar="COMx")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--reply-timeout", type=float, default=30.0,
                        help="等板端回包的秒数（一轮闭爪+七步约 6 s）")
    parser.add_argument("--camera-index", type=int, default=gp.DEFAULT_CAMERA_INDEX)
    parser.add_argument("--backend", choices=("dshow", "msmf", "any"), default="dshow")
    parser.add_argument("--calibration", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", choices=("auto", "cpu", "0"), default="auto")
    parser.add_argument("--exposure", type=int)
    parser.add_argument("--auto-exposure", action="store_true")
    args = parser.parse_args(argv)

    if not args.loop and args.cycles < 1:
        parser.error("--cycles 必须 >= 1（常驻模式用 --loop）")
    if args.log is None:
        args.log = RUNS_ROOT / ("g5_dynamic_%s" % time.strftime("%Y%m%d")) / "trials.jsonl"

    try:
        plan = load_plan(args)
    except SystemExit as exit_code:
        return int(exit_code.code or 2)
    except ValueError as error:
        print("G5_FAIL 配置不合法：%s" % error, file=sys.stderr)
        return 2

    cls = gp.CLASS_FILTER[args.class_name]
    try:
        calibration = PlaneCalibration.load(args.calibration)
        detector = Detector(args.model, device=args.device, imgsz=args.imgsz, conf=args.conf)
        camera = gp.open_camera(args.camera_index, args.backend, args.exposure,
                                args.auto_exposure)
    except (OSError, ValueError, RuntimeError, FileNotFoundError) as error:
        print("G5_FAIL stage=init %s" % error, file=sys.stderr)
        return 3

    link = None
    results = []
    try:
        link = Link(args)
        for _ in range(5):
            camera.read()            # 丢掉开流初期的过渡帧
        print("G5_READY %s：物块放到检测线上游（x%s%.0f），按 q 退出"
              % ("常驻模式" if args.loop else "跑 %d 轮" % args.cycles,
                 "<" if plan.direction > 0 else ">", plan.x_line_mm), flush=True)
        index = 0
        while True:
            index += 1
            if not args.loop and index > args.cycles:
                break
            results.append(one_cycle(args, calibration, detector, camera, link, plan,
                                     cls, index, args.log))
            poll_keys()
            if _STOP:
                print("G5_INFO 按 q 结束", flush=True)
                break
            if not args.dry_run:
                # 每轮结束臂已回到 exit 高位（--resume lift 跑完 place/retreat/exit），
                # 可以直接放下一件。这一行是给操作者的节拍提示。
                print("G5_INFO 放下一件到检测线上游（x%s%.0f）；按 q 退出"
                      % ("<" if plan.direction > 0 else ">", plan.x_line_mm), flush=True)
    except KeyboardInterrupt:
        print("G5_INFO interrupted", flush=True)
    finally:
        camera.close()
        if link is not None:
            link.close()

    hits = sum(1 for item in results if item.get("result") == "hit")
    print("G5_SUMMARY cycles=%d hits=%d misses=%d log=%s"
          % (len(results), hits, len(results) - hits, args.log), flush=True)
    return 0 if hits == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
