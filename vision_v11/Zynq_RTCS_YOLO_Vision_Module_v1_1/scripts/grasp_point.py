"""单次出点：多帧检测取中位数 -> 平面毫米坐标 -> 打印可直接粘贴到板端的命令。

流程（与 docs/视觉到抓取端到端流程.md 一致）：

  Camera --> Detector --> 每帧选一个目标 --> 多帧中位数 --> calibration.json 单应
          --> (x_mm, y_mm) --> g3_station_runner.py --grasp-xy

为什么多帧取中位数：单帧检测有 ±2~4 px 抖动（约 1~2 mm），中位数比均值抗离群；
`spread_px` 是这几帧中心点坐标的极差，它是抓取精度的上限，必须一起报出来。

坐标系：`config/calibration.json` 里的平面标定（原点=传送带角、+x 沿带长、+y 沿带宽），
**不在这里重新检测皮带**——标定文件就是正本，重检测会把当帧高光/遮挡抖进坐标里。
（确实是相机被碰过才用 `--calibration` 指向新文件，或用 belt_calibration_dynamic.py 重标。）

用法：
    .\\env.cmd scripts\\grasp_point.py --frames 9 --json

只在 PC 侧取点；不连板、不发运动帧。任何告警都只打印到 stderr，绝不阻断出点。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision.camera import Camera, BACKENDS
from vision.belt_detector import BeltDetector
from vision.detector import DEFAULT_MODEL, Detector
from vision.plane_calibration import DEFAULT_PATH, PlaneCalibration

DEFAULT_TABLE = Path(__file__).resolve().parents[3] / "config" / "grasp_teaching_table.json"
RUNS_ROOT = Path(__file__).resolve().parents[3] / "vision_runs"
DEFAULT_PLAN = "config/g3_station_plan.json"
DEFAULT_TEACH = "config/grasp_teaching_table.json"
CLASS_FILTER = {"any": None, "cube": 0, "cylinder": 1}
# 相机编号默认 1（现场机位）。同一个编号按后端依次试：先给的后端，
# 再 dshow / msmf / any —— 相机在、后端不对时不该直接判"没相机"。
DEFAULT_CAMERA_INDEX = 1
BACKEND_ORDER = ("dshow", "msmf", "any")


def pick_target(result, cls: int | None, calibration: "PlaneCalibration | None" = None,
                exclude_x: Sequence[float] = (), exclude_mm: float = 8.0,
                min_conf: float = 0.0):
    """每帧只取一个目标：**黄框（标定带面四边形）内 x 最大的那个**。

    2026-10-29 定（用户要求）：框里有多个可抓物时，优先抓最右边（x 最大）的那一件。
    物理理由与动态抓取是同一条：物块沿 +x 走，**最右边那件最先到拦截点**；静态下这条
    规则也无害——它把"先抓下游那件"固定成可复现的次序，而不是随置信度跳来跳去。

    **软 ROI**：给了标定就只在带面四边形内选。一个都没有时才退回"全体里 x 最大的"，
    不在这里硬拒——否则贴着带边放的方块会被自己的 ROI 判死；是否真的在带内由调用方
    （capture_agent 的 off_belt 检查）再判一次。

    **margin 仍然按置信度算**（选中的比次优的高多少）：改成按 x 排序后，这个差值依然是
    "两个都像"的唯一信号。10-25 实测夹爪会被检出成 Cube（conf 0.36~0.43）、真方块 0.79~0.80，
    差 0.4 时取哪个都行，差得少就说明当帧不可信。

    ``exclude_x`` / ``exclude_mm``（2026-10-31 加）：先按位置把候选剔掉，再选最优。
    **必须在选之前剔，不能选完再判**——否则剩下那件永远轮不到：带上有两件时，
    已抓过那件的位置上常驻着"被误检成 Cube 的夹爪"（conf 0.36~0.43），它 x 更大，
    每帧都被选成第一，选完再否掉就是"只抓一件、之后一直空转"。

    ``min_conf``：置信度门槛，同样在选之前过滤。夹爪误检、吸顶灯都远低于真方块
    （实测 0.26~0.43 vs 0.74~0.87），这道门槛与位置剔除互补。
    """
    items = [d for d in result.detections if cls is None or d.class_id == cls]
    if not items:
        return None, 0, None
    if calibration is not None:
        inside = [d for d in items if inside_belt(calibration, d.center_x, d.center_y)]
        if inside:
            items = inside
    if min_conf > 0:
        items = [d for d in items if d.confidence >= min_conf]
    if exclude_x and calibration is not None:
        items = [d for d in items
                 if not any(abs(_axis_x(calibration, d) - x) <= exclude_mm
                            for x in exclude_x)]
    if not items:
        return None, len(result.detections), None
    items.sort(key=lambda d: (_axis_x(calibration, d), d.confidence), reverse=True)
    chosen = items[0]
    others = [d.confidence for d in items[1:]]
    margin = chosen.confidence - max(others) if others else None
    return chosen, len(result.detections), margin


def _axis_x(calibration, item) -> float:
    """排序用的 x：有标定就用毫米（与抓取点同一坐标系，精确），否则退回像素。

    像素序与毫米序在标定单调时一致，但毫米序才是"下游优先"的真实含义，且透视项
    在画面边缘会让像素序与毫米序出现小差，直接用毫米省掉解释。
    """
    if calibration is None:
        return float(item.center_x)
    return calibration.to_mm(item.center_x, item.center_y)[0]


def open_camera(index: int, backend: str, exposure: int | None,
                auto_exposure: bool) -> Camera:
    """打开相机：固定 index，按后端顺序试（指定的后端优先）。

    编号不给就永远只试一个编号——"扫一遍 0~3 碰运气"会把镜头编号和机位问题混在一起，
    现场一旦换口又要重新猜。相机不在 1 就用 `--camera-index 0` 明说。
    """
    probes = [(index, backend)] + [(index, be) for be in BACKEND_ORDER if be != backend]
    last_error: Exception | None = None
    for idx, be in probes:
        try:
            cam = Camera(idx, backend=be).open()
        except RuntimeError as error:
            last_error = error
            continue
        cap = cam.capture
        if auto_exposure and cap is not None:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # DSHOW: 0.75=自动
        if exposure is not None and cap is not None:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # DSHOW: 0.25=手动
            cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure))
        actual = cam.actual
        print(f"GRASP_POINT_CAMERA index={idx} backend={be} "
              f"size={actual.get('width')}x{actual.get('height')} "
              f"fourcc={actual.get('fourcc')}", file=sys.stderr)
        return cam
    raise RuntimeError(f"没有可用相机：{last_error}")


def draw(frame, target, x_mm: float, y_mm: float):
    """取证图：画框 + 中心 + 毫米坐标。"""
    image = frame.copy()
    if target is not None:
        x1, y1, x2, y2 = (round(v) for v in target.bbox_xyxy)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 210, 0), 2)
        cv2.circle(image, (round(target.center_x), round(target.center_y)), 4, (0, 0, 255), -1)
    text = f"({x_mm:.1f}, {y_mm:.1f}) mm  {time.strftime('%H:%M:%S')}"
    cv2.putText(image, text, (12, image.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (0, 0, 255) if target is not None else (128, 128, 128), 2)
    return image


def inside_belt(calibration: PlaneCalibration, px: float, py: float) -> bool:
    """中心点是否落在标定的带面四边形内。

    这条检查是 10-25 实测逼出来的：相机没对准（或带面不在画面里）时，模型会把吸顶灯
    当 Cube 检出，conf 0.30~0.36，`--conf 0.25` 拦不住；这个点一旦喂给 --grasp-xy，
    插值两端夹住会变成"任意的合法姿态"，臂会去抓空气。**只告警不阻断**。
    """
    quad = np.array(calibration.corners_px, dtype=np.float32)
    return cv2.pointPolygonTest(quad, (float(px), float(py)), False) >= 0


def quad_iou(a, b) -> float:
    """两个凸四边形的 IoU，用来判断"当前看到的带面"是否还是标定时那块。"""
    ha = cv2.convexHull(np.asarray(a, dtype=np.float32))
    hb = cv2.convexHull(np.asarray(b, dtype=np.float32))
    inter, _ = cv2.intersectConvexConvex(ha, hb)
    area_a = abs(cv2.contourArea(ha))
    area_b = abs(cv2.contourArea(hb))
    union = area_a + area_b - inter
    return float(inter / union) if union > 1e-6 else 0.0


def check_aim(calibration: PlaneCalibration, frame) -> tuple[float | None, str | None]:
    """带面在不在画面里、还是不是标定时那块。

    返回 (iou, 告警)。iou=None 表示根本没检出带面。相机被碰过 / 换机位后，
    `calibration.json` 立刻失效，而**失效的标定不会报错**——它照样给出"看起来合理"的
    毫米坐标，整批试验就全废。所以每取一次点都验一遍。
    """
    belt = BeltDetector(calibration.board_mm[0], calibration.board_mm[1])
    if not belt.detect(frame):
        return None, ("belt_not_detected (画面里找不到绿色带面：相机没对准/被遮挡/"
                      "带面不在视野，坐标不可用)")
    iou = quad_iou(belt.corners_px, calibration.corners_px)
    if iou < 0.5:
        return iou, (f"belt_quad_mismatch iou={iou:.2f} (当前带面与标定差太多：相机被碰过，"
                     f"需重跑 belt_calibration_dynamic.py 重标)")
    return iou, None


def load_lane(table_path: Path | None) -> dict | None:
    """读示教表拿到已教区间与车道 y；读不到只告警。"""
    if table_path is None:
        return None
    try:
        raw = json.loads(Path(table_path).read_text(encoding="utf-8"))
        xs = [float(p["x_mm"]) for p in raw]
        ys = [float(p["y_mm"]) for p in raw]
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"GRASP_POINT_WARN teaching_table_unreadable {error}", file=sys.stderr)
        return None
    return {"x_lo": min(xs), "x_hi": max(xs), "y_med": statistics.median(ys),
            "points": len(xs)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frames", type=int, default=9, help="采样帧数（默认 9）")
    parser.add_argument("--json", action="store_true", help="stdout 只输出一行 JSON")
    parser.add_argument("--camera-index", type=int, default=DEFAULT_CAMERA_INDEX,
                        help=f"相机编号（默认 {DEFAULT_CAMERA_INDEX}）")
    parser.add_argument("--backend", choices=tuple(BACKENDS), default="dshow")
    parser.add_argument("--calibration", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", choices=("auto", "cpu", "0"), default="auto")
    parser.add_argument("--class-name", choices=tuple(CLASS_FILTER), default="any",
                        help="只抓某一类；默认任何类里置信度最高的")
    parser.add_argument("--exposure", type=int, help="手动曝光（DSHOW 负值更暗）")
    parser.add_argument("--auto-exposure", action="store_true", help="强制自动曝光")
    parser.add_argument("--teaching-table", type=Path, default=DEFAULT_TABLE,
                        help="只用于告警：判断是否超出示教区间")
    parser.add_argument("--log", type=Path, help="追加一行 JSONL，便于统计成功率")
    parser.add_argument("--trial", type=int, metavar="N",
                        help="试验编号：自动把 JSONL 与带框取证图写进 vision_runs/closedloop_<日期>/")
    parser.add_argument("--save-annotated", type=Path, help="存一张带框取证图")
    parser.add_argument("--warmup", type=int, default=5, help="正式采样前丢弃的帧数")
    parser.add_argument("--no-aim-check", action="store_true",
                        help="跳过带面位置校验（默认每轮都验）")
    args = parser.parse_args(argv)

    if args.frames < 1:
        parser.error("--frames 必须 >= 1")

    # --trial N：证据路径固定下来，避免 10 轮试验靠手工抄数、抄错编号。
    if args.trial is not None:
        run_dir = RUNS_ROOT / f"closedloop_{time.strftime('%Y%m%d')}"
        if args.log is None:
            args.log = run_dir / "points.jsonl"
        if args.save_annotated is None:
            args.save_annotated = run_dir / f"run{args.trial:02d}.png"

    start = time.monotonic()
    try:
        calibration = PlaneCalibration.load(args.calibration)
        detector = Detector(args.model, device=args.device, imgsz=args.imgsz, conf=args.conf)
        camera = open_camera(args.camera_index, args.backend, args.exposure,
                             args.auto_exposure)
    except (OSError, ValueError, RuntimeError, FileNotFoundError) as error:
        print(f"GRASP_POINT_FAIL stage=init {error}", file=sys.stderr)
        return 3

    cls = CLASS_FILTER[args.class_name]
    centers_px: list[tuple[float, float]] = []
    confs: list[float] = []
    names: list[str] = []
    det_counts: list[int] = []
    margins: list[float] = []
    last_frame = None
    try:
        for _ in range(max(0, args.warmup)):
            camera.read()  # 丢掉开流初期的自动曝光/白平衡过渡帧
        while len(centers_px) < args.frames:
            frame = camera.read()
            last_frame = frame
            try:
                result = detector.detect(frame)
            except ValueError as error:
                print(f"GRASP_POINT_WARN detect_skipped {error}", file=sys.stderr)
                continue
            target, n_all, margin = pick_target(result, cls, calibration)
            det_counts.append(n_all)
            if margin is not None:
                margins.append(margin)
            if target is None:
                continue
            centers_px.append((target.center_x, target.center_y))
            confs.append(target.confidence)
            names.append(target.class_name)
    finally:
        camera.close()

    if not centers_px:
        print(f"GRASP_POINT_FAIL stage=detect no_target frames={args.frames}", file=sys.stderr)
        if args.json:
            print(json.dumps({"x_mm": None, "y_mm": None, "frames_used": 0,
                              "frames_total": args.frames, "conf": None,
                              "warnings": ["no_target"]}, ensure_ascii=False))
        return 4

    mx = statistics.median(p[0] for p in centers_px)
    my = statistics.median(p[1] for p in centers_px)
    x_mm, y_mm = calibration.to_mm(mx, my)
    xs = [p[0] for p in centers_px]
    ys = [p[1] for p in centers_px]
    spread_px = (max(xs) - min(xs), max(ys) - min(ys))
    (x0m, y0m) = calibration.to_mm(min(xs), min(ys))
    (x1m, y1m) = calibration.to_mm(max(xs), max(ys))
    spread_mm = (abs(x1m - x0m), abs(y1m - y0m))
    conf_med = statistics.median(confs)

    warnings: list[str] = []
    iou, aim_warning = (None, None)
    if not args.no_aim_check and last_frame is not None:
        iou, aim_warning = check_aim(calibration, last_frame)
        if aim_warning:
            warnings.append(aim_warning)
    if len(centers_px) < args.frames:
        warnings.append(f"frames_used={len(centers_px)}/{args.frames}")
    if max(det_counts, default=0) > 1:
        warnings.append(f"multi_detection_max={max(det_counts)} (取最高置信度)")
    if margins and min(margins) < 0.15:
        warnings.append(f"ambiguous_target min_margin={min(margins):.2f} "
                        f"(两个目标置信度太接近，可能是夹爪/背景被当成工件)")
    if conf_med < 0.45:
        warnings.append(f"low_conf {conf_med:.2f} (<0.45，误检风险高)")
    if not inside_belt(calibration, mx, my):
        warnings.append("outside_belt_quad (中心不在标定带面内，极可能是误检/相机没对准)")
    if spread_mm[0] > 3.0 or spread_mm[1] > 3.0:
        warnings.append(f"spread_large x={spread_mm[0]:.1f}mm y={spread_mm[1]:.1f}mm")
    lane = load_lane(args.teaching_table)
    if lane:
        if not lane["x_lo"] <= x_mm <= lane["x_hi"]:
            warnings.append(f"x_outside_taught {lane['x_lo']:.0f}..{lane['x_hi']:.0f} "
                            f"(会被插值两端夹住，不会外推)")
        if abs(y_mm - lane["y_med"]) > 8.0:
            warnings.append(f"y_off_lane {y_mm - lane['y_med']:+.1f}mm "
                            f"(车道 y={lane['y_med']:.0f}，表只有这一条车道)")

    command = (f"sudo python3 scripts/g3_station_runner.py {DEFAULT_PLAN} --uio /dev/uio0 "
               f"--grasp-xy {x_mm:.1f},{y_mm:.1f} --teaching-table {DEFAULT_TEACH} --once")
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "trial": args.trial,
        "x_mm": round(x_mm, 2), "y_mm": round(y_mm, 2),
        "center_px": [round(mx, 2), round(my, 2)],
        "conf": round(conf_med, 4),
        "conf_margin": round(min(margins), 3) if margins else None,
        "class_name": statistics.mode(names) if names else None,
        "frames_used": len(centers_px), "frames_total": args.frames,
        "spread_px": [round(spread_px[0], 2), round(spread_px[1], 2)],
        "spread_mm": [round(spread_mm[0], 2), round(spread_mm[1], 2)],
        "camera": camera.actual,
        "calibration": str(args.calibration),
        "inside_belt_quad": bool(inside_belt(calibration, mx, my)),
        "belt_iou": None if iou is None else round(iou, 3),
        "elapsed_s": round(time.monotonic() - start, 2),
        "warnings": warnings,
        "board_command": command,
    }

    if args.save_annotated is not None and last_frame is not None:
        try:
            args.save_annotated.parent.mkdir(parents=True, exist_ok=True)
            target, _, _ = pick_target(detector.detect(last_frame), cls, calibration)
            cv2.imwrite(str(args.save_annotated), draw(last_frame, target, x_mm, y_mm))
        except (OSError, ValueError) as error:
            print(f"GRASP_POINT_WARN annotated_failed {error}", file=sys.stderr)

    if args.log is not None:
        try:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            with args.log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as error:
            print(f"GRASP_POINT_WARN log_failed {error}", file=sys.stderr)

    for warning in warnings:
        print(f"GRASP_POINT_WARN {warning}", file=sys.stderr)

    if args.json:
        print(json.dumps(record, ensure_ascii=False))
        return 0

    print(f"GRASP_POINT x_mm={x_mm:.1f} y_mm={y_mm:.1f} conf={conf_med:.2f} "
          f"cls={record['class_name']} frames={len(centers_px)}/{args.frames} "
          f"spread_px=({spread_px[0]:.1f},{spread_px[1]:.1f}) "
          f"spread_mm=({spread_mm[0]:.1f},{spread_mm[1]:.1f})")
    print("BOARD_CMD " + command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
