"""单图检测入口；不打开摄像头。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration import to_ps_payload
from vision import Detector
from vision.visualizer import draw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="单张图片识别 Cube/Cylinder")
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, help="可选：带框图片保存路径")
    parser.add_argument("--device", choices=("auto", "cpu", "0"), default="auto")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args(argv)
    if not args.image.is_file():
        raise FileNotFoundError(args.image)
    frame = cv2.imdecode(np.fromfile(args.image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"无法读取图片：{args.image}")
    detector = Detector(device=args.device, imgsz=args.imgsz, conf=args.conf)
    result = detector.detect(frame)
    print(json.dumps(to_ps_payload(result), ensure_ascii=False, indent=2))
    if args.output:
        if args.output.exists():
            raise FileExistsError(f"拒绝覆盖：{args.output}")
        image = draw(frame, result, 0.0, detector.device)
        ok, encoded = cv2.imencode(args.output.suffix, image)
        if not ok:
            raise ValueError(f"无法编码图片：{args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        encoded.tofile(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
