"""检测结果绘制；不访问模型和摄像头。"""
from __future__ import annotations

import cv2

from .results import FrameResult


COLORS = {0: (0, 210, 0), 1: (0, 150, 255)}


def draw(frame_bgr, result: FrameResult, fps: float, device: str):
    """返回带框副本，保留原始帧内容与尺寸。"""
    image = frame_bgr.copy()
    for item in result.detections:
        color = COLORS[item.class_id]
        x1, y1, x2, y2 = (round(v) for v in item.bbox_xyxy)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        cv2.circle(image, (round(item.center_x), round(item.center_y)), 4, color, -1)
        label = f"{item.class_name} {item.confidence:.2f} ({item.center_x:.0f},{item.center_y:.0f})"
        cv2.putText(image, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    cv2.putText(image, f"FPS {fps:.1f} | {device} | Q quit", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return image
