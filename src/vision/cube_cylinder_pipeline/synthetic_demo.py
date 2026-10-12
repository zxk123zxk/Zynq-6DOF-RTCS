"""Generate a deterministic synthetic geometry demonstration."""
# SPDX-License-Identifier: AGPL-3.0-only
# 职责：生成确定性合成 cube/cylinder 顶视轮廓，演示接口与像素坐标，不代表真实相机性能。

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .opencv_geometry_detector import BackgroundDifferenceMaskConfig, OpenCVGeometryDetector


def synthetic_frame() -> np.ndarray:
    """返回 640×360 BGR 合成图：一个旋转方形和一个圆形顶视轮廓。"""
    frame = np.full((360, 640, 3), (30, 30, 30), dtype=np.uint8)
    square = cv2.boxPoints(((180, 180), (90, 90), 18)).astype(np.int32)
    cv2.fillConvexPoly(frame, square, (220, 220, 220), lineType=cv2.LINE_8)
    cv2.circle(frame, (440, 180), 48, (220, 220, 220), thickness=-1, lineType=cv2.LINE_8)
    return frame


def write_png(path: Path, image: np.ndarray) -> None:
    """保存 PNG 诊断图；编码失败时抛出 ``RuntimeError``。"""
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"failed to encode {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(path)


def main() -> int:
    """运行合成几何演示并保存输入、Mask、标注图与 JSON 证据。

    时间戳和 Workspace 毫米坐标均明确不可用，结果只能作为合成测试证据。
    """
    output = Path(__file__).resolve().parent / "artifacts"
    output.mkdir(parents=True, exist_ok=True)
    frame = synthetic_frame()
    empty_background = np.full_like(frame, (30, 30, 30))
    detector = OpenCVGeometryDetector(
        BackgroundDifferenceMaskConfig(
            background_bgr=(30, 30, 30), distance_threshold=60, morphology_kernel_px=3
        )
    )
    result, mask, diagnostics = detector.detect(
        frame,
        frame_index=0,
        timestamp_s=None,
        timestamp_kind="not_available_for_synthetic_still",
    )
    annotated = frame.copy()
    colors = {0: (0, 255, 0), 1: (0, 165, 255)}
    for detection in result.detections:
        x1, y1, x2, y2 = (int(round(value)) for value in detection.bbox_xyxy_px)
        u, v = (int(round(value)) for value in detection.center_px)
        color = colors[detection.class_id]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.drawMarker(annotated, (u, v), color, cv2.MARKER_CROSS, 15, 2)
        cv2.putText(
            annotated,
            f"{detection.class_name} {detection.confidence:.2f}",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )
    write_png(output / "00_empty_background.png", empty_background)
    write_png(output / "01_synthetic_input.png", frame)
    write_png(output / "02_foreground_mask.png", mask)
    write_png(output / "03_detections.png", annotated)
    payload = result.to_dict() | {
        "diagnostics": [diagnostic.__dict__ for diagnostic in diagnostics],
        "evidence_type": "synthetic_test_only",
        "workspace_coordinates": "not_available_without_real_calibration",
    }
    (output / "detections.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
