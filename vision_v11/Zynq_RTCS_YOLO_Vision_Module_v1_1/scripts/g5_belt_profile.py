"""带速/方向实测：用抓取点同一套相机 + YOLO + 单应，直接量出 mm/s。

为什么不用尺子加秒表：带速进的是 `T_flight = 距离 ÷ 带速`，距离来自 `calibration.json`
的毫米坐标，所以带速也必须是**同一坐标系**里的毫米。外部量出来的是"真实 mm/s"，
两者只差标定的比例误差（2% 量级，在 6 s 的飞行时间上无所谓）；但用同一坐标系量，
还能顺手得到"每帧走多远"和"每帧耗时"——那两样才是动态触发真正依赖的量。

用法：

    .\\env.cmd scripts\\g5_belt_profile.py --seconds 6
    .\\env.cmd scripts\\g5_belt_profile.py --seconds 6 --write-config

做法规矩：物块放在上游、开带、让它整段走完；本脚本只读帧不出点、不连板、不发任何指令。
偏离（含被遮挡、丢帧）只告警不阻断——按 /CLAUDE.md 不做硬门禁。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grasp_point as gp
from vision.detector import DEFAULT_MODEL, Detector
from vision.plane_calibration import DEFAULT_PATH, PlaneCalibration

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "g5_dynamic.json"
# 物块被遮挡或出画时，前后两段不能拼成一条直线——间隔超过这个秒数就另起一段。
SEGMENT_GAP_S = 0.5
# 低于这个置信度的样本不进拟合：背景误检会把斜率拉歪，而拟合对离群点很敏感。
MIN_CONF = 0.45


def fit_speed(samples):
    """最小二乘拟合 x(t)；返回 (速度 mm/s, 截距, 残差 RMS mm)。"""
    times = np.array([s[0] for s in samples], dtype=float)
    xs = np.array([s[1] for s in samples], dtype=float)
    times = times - times[0]
    slope, intercept = np.polyfit(times, xs, 1)
    residual = xs - (slope * times + intercept)
    return float(slope), float(intercept), float(np.sqrt(np.mean(residual ** 2)))


def longest_segment(samples):
    """取最长的一段连续采样；跨遮挡/出画的样本不能混在一起做拟合。"""
    if not samples:
        return []
    best, current = [], [samples[0]]
    for previous, item in zip(samples, samples[1:]):
        if item[0] - previous[0] > SEGMENT_GAP_S:
            if len(current) > len(best):
                best = current
            current = []
        current.append(item)
    return current if len(current) > len(best) else best


def write_config(speed_mm_s: float, direction: str, samples: int) -> None:
    """把实测值写回 config/g5_dynamic.json（只改 belt 段，其余原样保留）。"""
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    data["belt"]["direction"] = direction
    data["belt"]["speed_mm_s"] = round(abs(speed_mm_s), 2)
    data["belt"]["speed_measured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["belt"]["speed_method"] = "g5_belt_profile.py samples=%d" % samples
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("WROTE_CONFIG %s belt.speed_mm_s=%.2f direction=%s"
          % (CONFIG, abs(speed_mm_s), direction), flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=6.0, help="采样时长（秒）")
    parser.add_argument("--class-name", choices=tuple(gp.CLASS_FILTER), default="any")
    parser.add_argument("--write-config", action="store_true",
                        help="把实测速度/方向写回 config/g5_dynamic.json")
    parser.add_argument("--log", type=Path, help="追加一行 JSONL（证据留痕）")
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

    try:
        calibration = PlaneCalibration.load(args.calibration)
        detector = Detector(args.model, device=args.device, imgsz=args.imgsz, conf=args.conf)
        camera = gp.open_camera(args.camera_index, args.backend, args.exposure,
                                args.auto_exposure)
    except (OSError, ValueError, RuntimeError, FileNotFoundError) as error:
        print("BELT_PROFILE_FAIL stage=init %s" % error, file=sys.stderr)
        return 3

    cls = gp.CLASS_FILTER[args.class_name]
    samples: list[tuple[float, float, float, float]] = []   # (t, x_mm, y_mm, conf)
    frame_ms: list[float] = []
    started = time.monotonic()
    last_frame_t = None
    try:
        for _ in range(5):
            camera.read()            # 丢掉开流初期的自动曝光/白平衡过渡帧
        print("BELT_PROFILE_START seconds=%.1f only=%s（开带让物块走完，"
              "Ctrl-C 提前结束）" % (args.seconds, args.class_name), flush=True)
        while time.monotonic() - started < args.seconds:
            frame = camera.read()
            now = time.monotonic()
            if last_frame_t is not None:
                frame_ms.append(1000.0 * (now - last_frame_t))
            last_frame_t = now
            try:
                result = detector.detect(frame)
            except ValueError as error:
                print("BELT_PROFILE_WARN detect_skipped %s" % error, file=sys.stderr)
                continue
            target, _n_all, _margin = gp.pick_target(result, cls, calibration)
            if target is None or target.confidence < MIN_CONF:
                continue
            if not gp.inside_belt(calibration, target.center_x, target.center_y):
                continue                 # 带面外的误检不参与拟合
            x_mm, y_mm = calibration.to_mm(target.center_x, target.center_y)
            samples.append((now, x_mm, y_mm, target.confidence))
    except KeyboardInterrupt:
        print("BELT_PROFILE_INFO interrupted", flush=True)
    finally:
        camera.close()

    segment = longest_segment(samples)
    if len(segment) < 5:
        print("BELT_PROFILE_FAIL 有效样本只有 %d 帧（需要 >=5）：物块没进画面、"
              "或带速太慢没走出位移、或类别过滤把目标排掉了" % len(segment))
        return 4

    speed, _intercept, residual_rms = fit_speed(segment)
    span_s = segment[-1][0] - segment[0][0]
    y_values = [s[2] for s in segment]
    conf_med = statistics.median(s[3] for s in segment)
    p50 = statistics.median(frame_ms) if frame_ms else float("nan")
    p95 = (sorted(frame_ms)[int(0.95 * (len(frame_ms) - 1))] if frame_ms else float("nan"))
    direction = "+x" if speed > 0 else "-x"

    print("BELT_SPEED v_mm_s=%.2f direction=%s samples=%d span_s=%.2f "
          "residual_rms_mm=%.2f" % (abs(speed), direction, len(segment), span_s,
                                    residual_rms), flush=True)
    print("BELT_PROFILE y_span_mm=%.1f conf_med=%.2f frame_ms_p50=%.0f frame_ms_p95=%.0f"
          % (max(y_values) - min(y_values), conf_med, p50, p95), flush=True)

    if len(segment) < len(samples):
        print("BELT_PROFILE_WARN 丢弃了 %d 帧不连续的样本（遮挡/出画后重新出现）"
              % (len(samples) - len(segment)), flush=True)
    if abs(speed) < 5.0:
        print("BELT_PROFILE_WARN 速度 <5 mm/s：可能带子没开，或物块卡住", flush=True)
    if residual_rms > 2.0:
        print("BELT_PROFILE_WARN 残差 %.1f mm 偏大：带面打滑、检测框跳动，"
              "或物块在带上不是匀速" % residual_rms, flush=True)
    if direction == "-x":
        print("BELT_PROFILE_WARN 方向为 -x：拦截点必须在检测线上游（x 更小），"
              "config 里 direction 要改成 -x", flush=True)

    record = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "speed_mm_s": round(abs(speed), 2), "direction": direction,
              "samples": len(segment), "span_s": round(span_s, 2),
              "residual_rms_mm": round(residual_rms, 3),
              "y_span_mm": round(max(y_values) - min(y_values), 2),
              "conf_med": round(conf_med, 3),
              "frame_ms_p50": None if not frame_ms else round(p50, 1),
              "frame_ms_p95": None if not frame_ms else round(p95, 1),
              "class_filter": args.class_name}
    if args.log:
        try:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            with args.log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as error:
            print("BELT_PROFILE_WARN log_failed %s" % error, file=sys.stderr)
    if args.write_config:
        write_config(speed, direction, len(segment))
    return 0


if __name__ == "__main__":
    sys.exit(main())
