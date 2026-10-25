"""实时识别 + 动态传送带检测（无需手动标定）。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision.belt_detector import BeltDetector
from vision.camera import Camera
from vision.detector import Detector
from vision.results import FrameResult
from integration.ps_payload import to_ps_payload


COLORS = {0: (0, 210, 0), 1: (0, 150, 255)}


def draw_with_belt(frame_bgr, result: FrameResult, fps: float, belt: BeltDetector):
    """绘制检测结果 + 传送带边界。"""
    image = frame_bgr.copy()

    # 绘制传送带边界
    if belt.is_ready():
        corners = [tuple(map(int, pt)) for pt in belt.corners_px]
        for i in range(4):
            cv2.line(image, corners[i], corners[(i + 1) % 4], (0, 255, 255), 2)
        labels = ["BL(0,0)", "BR", "TR", "TL"]
        for corner, label in zip(corners, labels):
            cv2.circle(image, corner, 5, (0, 255, 255), -1)
            cv2.putText(image, label, (corner[0] + 8, corner[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
    else:
        cv2.putText(image, "Detecting belt...", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    # 绘制检测框
    for item in result.detections:
        color = COLORS[item.class_id]
        x1, y1, x2, y2 = (round(v) for v in item.bbox_xyxy)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        cv2.circle(image, (round(item.center_x), round(item.center_y)), 4, color, -1)
        label = f"{item.class_name} {item.confidence:.2f}"
        cv2.putText(image, label, (x1, max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        if belt.is_ready():
            try:
                x_mm, y_mm = belt.to_mm(item.center_x, item.center_y)
                _, top_mm = belt.to_mm(item.center_x, item.bbox_xyxy[1])
                _, bottom_mm = belt.to_mm(item.center_x, item.bbox_xyxy[3])
                cv2.putText(image, f"X={x_mm:.1f} Y={y_mm:.1f}",
                            (x1, min(image.shape[0] - 6, y2 + 18)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                if item.class_name == "Cube":
                    cv2.putText(image, f"top Y={top_mm:.1f} bot Y={bottom_mm:.1f}",
                                (x1, min(image.shape[0] - 26, y2 + 38)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            except RuntimeError:
                pass

    cv2.putText(image, f"FPS {fps:.1f} | Dynamic Belt | Q quit", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description="动态传送带检测 + 实时识别")
    parser.add_argument("--camera-index", type=int, default=1)
    parser.add_argument("--backend", choices=("dshow", "msmf", "any"), default="msmf")
    parser.add_argument("--width", type=int, help="固定分辨率宽度（不传则自动探测 MJPG 模式）")
    parser.add_argument("--height", type=int, help="固定分辨率高度（不传则自动探测）")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--belt-width", type=float, default=490.0,
                        help="传送带实际宽度（毫米）")
    parser.add_argument("--belt-height", type=float, default=80.0,
                        help="传送带实际高度（毫米）")
    parser.add_argument("--no-display", action="store_true",
                        help="不显示窗口，仅输出 JSON")
    args = parser.parse_args()

    try:
        detector = Detector(imgsz=args.imgsz, conf=args.conf)
        belt = BeltDetector(belt_width_mm=args.belt_width,
                           belt_height_mm=args.belt_height)
        print(f"YOLO 模型已加载，传送带尺寸：{args.belt_width} x {args.belt_height} mm", flush=True)
    except Exception as e:
        print(f"模型加载失败：{e}", file=sys.stderr)
        return 1

    try:
        with Camera(args.camera_index, backend=args.backend,
                    width=args.width, height=args.height) as camera:
            actual_width = camera.actual["width"]
            actual_height = camera.actual["height"]
            print(f"摄像头分辨率：{actual_width}x{actual_height} "
                  f"{camera.actual.get('fourcc', 'unknown')}", flush=True)

            window = None if args.no_display else "Dynamic Belt Detection"
            if window:
                cv2.namedWindow(window, cv2.WINDOW_NORMAL)

            frame_count = 0
            start_time = time.perf_counter()

            while True:
                frame = camera.read()

                # 每帧检测传送带
                belt.detect(frame)

                # YOLO 检测
                result = detector.detect(frame)

                # 构建输出 JSON
                payload = {
                    "frame_index": frame_count,
                    "timestamp_monotonic_s": time.perf_counter(),
                    "belt_detected": belt.is_ready(),
                    "detections": []
                }

                for d in result.detections:
                    x1, y1, x2, y2 = d.bbox_xyxy
                    item = {
                        "class_id": d.class_id,
                        "class_name": d.class_name,
                        "confidence": d.confidence,
                        "bbox_xyxy": [x1, y1, x2, y2],
                        "center_x": d.center_x,
                        "center_y": d.center_y,
                    }
                    if belt.is_ready():
                        try:
                            x_mm, y_mm = belt.to_mm(d.center_x, d.center_y)
                            left_mm, _ = belt.to_mm(x1, d.center_y)
                            right_mm, _ = belt.to_mm(x2, d.center_y)
                            _, top_mm = belt.to_mm(d.center_x, y1)
                            _, bottom_mm = belt.to_mm(d.center_x, y2)
                            item["center_x_mm"] = x_mm
                            item["center_y_mm"] = y_mm
                            item["bbox_mm"] = {
                                "left": left_mm, "right": right_mm,
                                "top": top_mm, "bottom": bottom_mm,
                                "width": abs(right_mm - left_mm),
                                "height": abs(bottom_mm - top_mm)
                            }
                        except RuntimeError:
                            pass
                    payload["detections"].append(item)

                print(json.dumps(payload, ensure_ascii=False), flush=True)

                if window:
                    elapsed = time.perf_counter() - start_time
                    fps = (frame_count + 1) / max(elapsed, 1e-6)
                    cv2.imshow(window, draw_with_belt(frame, result, fps, belt))
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord('q'), ord('Q'), 27):
                        break
                    if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                        break

                frame_count += 1

    except KeyboardInterrupt:
        print("\n用户中断", file=sys.stderr)
    except Exception as e:
        print(f"运行错误：{e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if window:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
