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
from vision.visualizer import draw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USB Camera 实时识别 Cube/Cylinder")
    parser.add_argument("--camera-index", type=int, default=1)
    parser.add_argument("--backend", choices=("dshow", "msmf", "any"), default="dshow")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", choices=("auto", "cpu", "0"), default="auto")
    parser.add_argument("--auto-exposure", type=float, default=None,
                        help="CAP_PROP_AUTO_EXPOSURE 手动/自动开关（Windows MSMF 0.75=手动；V4L2 1=手动 3=自动）")
    parser.add_argument("--exposure", type=float, default=None,
                        help="CAP_PROP_EXPOSURE 手动曝光（Windows 常为 log2 秒，越小越暗）")
    parser.add_argument("--gain", type=float, default=None, help="CAP_PROP_GAIN 增益")
    parser.add_argument("--check-model", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="保存 annotated.mp4 + detections.jsonl + summary.json 的目录（必须不存在，避免覆盖证据）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    detector = Detector(device=args.device, imgsz=args.imgsz, conf=args.conf)
    print(f"模型已加载：best.pt，设备：{detector.device}，类别：{{0: 'cube', 1: 'cylinder'}}", flush=True)
    if args.check_model:
        return 0
    output_dir = args.output_dir
    jsonl = None
    writer = None
    frame_count = 0
    if output_dir is not None:
        if output_dir.exists():
            print(f"输出目录已存在，拒绝覆盖：{output_dir}", file=sys.stderr)
            return 1
        output_dir.mkdir(parents=True)
        jsonl = (output_dir / "detections.jsonl").open("w", encoding="utf-8")
    try:
        with Camera(args.camera_index, backend=args.backend,
                    width=args.width, height=args.height,
                    auto_exposure=args.auto_exposure, exposure=args.exposure,
                    gain=args.gain) as camera:
            actual_width = int(camera.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(camera.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"摄像头实际分辨率：{actual_width}x{actual_height}", flush=True)
            if camera.controls:
                print(f"相机控制回读：{camera.controls}", flush=True)
            last = time.perf_counter()
            for index in range(args.max_frames if args.max_frames > 0 else sys.maxsize):
                frame = camera.read()
                result = detector.detect(frame)
                now = time.perf_counter()
                fps = 1 / max(now - last, 1e-9)
                last = now
                image = draw(frame, result, fps, detector.device)
                payload = to_ps_payload(result)
                record = {"frame_index": index, "timestamp_monotonic_s": now,
                          "detections": payload["detections"]}
                print(json.dumps(record, ensure_ascii=False), flush=True)
                if jsonl is not None:
                    jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
                    jsonl.flush()
                if output_dir is not None:
                    if writer is None:
                        writer = cv2.VideoWriter(str(output_dir / "annotated.mp4"),
                                                 cv2.VideoWriter_fourcc(*"mp4v"), 15.0,
                                                 (frame.shape[1], frame.shape[0]))
                    writer.write(image)
                frame_count = index + 1
                cv2.imshow("Cube/Cylinder Camera Demo - Q quit", image)
                if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                    break
    finally:
        cv2.destroyAllWindows()
        if jsonl is not None:
            jsonl.close()
        if writer is not None:
            writer.release()
        if output_dir is not None:
            summary = {"status": "complete", "source": "camera", "mode": "yolo",
                       "frames": frame_count, "output": str(output_dir.resolve()),
                       "model": "best.pt", "device": detector.device}
            (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
            print(f"已保存到 {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
