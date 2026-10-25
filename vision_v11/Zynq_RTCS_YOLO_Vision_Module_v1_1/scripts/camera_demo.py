"""V1.1 摄像头入口；保留 V1.0 参数和逐帧 JSON 基本格式。"""
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration import to_ps_payload
from vision import Detector
from vision.camera import Camera
from vision.plane_calibration import DEFAULT_PATH, PlaneCalibration
from vision.visualizer import draw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USB Camera 实时识别 Cube/Cylinder")
    parser.add_argument("--camera-index", type=int, default=1)
    parser.add_argument("--backend", choices=("dshow", "msmf", "any"), default="msmf")
    parser.add_argument("--width", type=int, default=1280,
                        help="相机分辨率宽度，必须与 belt_calibration_dynamic.py 一致")
    parser.add_argument("--height", type=int, default=720,
                        help="相机分辨率高度，必须与 belt_calibration_dynamic.py 一致")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", choices=("auto", "cpu", "0"), default="auto")
    parser.add_argument("--check-model", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_PATH,
                        help="live_calibration.py 保存的平面标定；文件不存在时只输出像素")
    parser.add_argument("--no-calibration", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    detector = Detector(device=args.device, imgsz=args.imgsz, conf=args.conf)
    print(f"模型已加载：best.pt，设备：{detector.device}，类别：{{0: 'cube', 1: 'cylinder'}}", flush=True)
    if args.check_model:
        return 0
    try:
        with Camera(args.camera_index, backend=args.backend,
                    width=args.width, height=args.height) as camera:
            actual_width = camera.actual["width"]
            actual_height = camera.actual["height"]
            print(f"摄像头实际分辨率：{actual_width}x{actual_height} "
                  f"{camera.actual.get('fourcc','')} {camera.actual.get('fps','')}fps", flush=True)
            calibration = None
            if not args.no_calibration and args.calibration.is_file():
                calibration = PlaneCalibration.load(args.calibration)
                if calibration.image_size != (actual_width, actual_height):
                    raise SystemExit(f"标定分辨率 {calibration.image_size} 与摄像头 "
                                     f"{actual_width}x{actual_height} 不一致，请重新运行 live_calibration.py")
                print(f"已加载平面标定：{args.calibration}", flush=True)
            last = time.perf_counter()
            for index in range(args.max_frames if args.max_frames > 0 else sys.maxsize):
                frame = camera.read()
                result = detector.detect(frame)
                now = time.perf_counter()
                fps = 1 / max(now - last, 1e-9)
                last = now
                image = draw(frame, result, fps, detector.device, calibration)
                payload = to_ps_payload(result, calibration)
                print(json.dumps({"frame_index": index, "timestamp_monotonic_s": now,
                                  "detections": payload["detections"]}, ensure_ascii=False), flush=True)
                # 缩放显示：原始帧可能超出屏幕
                h, w = image.shape[:2]
                scale = min(1.0, 1280 / w, 720 / h)
                display = cv2.resize(image, (round(w * scale), round(h * scale))) if scale < 1 else image
                cv2.imshow("Cube/Cylinder Camera Demo - Q quit", display)
                if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                    break
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
