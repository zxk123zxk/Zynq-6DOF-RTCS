"""检测结果绘制；不访问模型和摄像头。"""
from __future__ import annotations

import cv2

from .results import FrameResult


COLORS = {0: (0, 210, 0), 1: (0, 150, 255)}


def draw(frame_bgr, result: FrameResult, fps: float, device: str, calibration=None):
    """返回带框副本，保留原始帧内容与尺寸；给出标定时标注毫米坐标和边界。"""
    image = frame_bgr.copy()

    # 绘制传送带标定区域边界
    if calibration is not None:
        corners = [tuple(map(int, pt)) for pt in calibration.corners_px]
        for i in range(4):
            cv2.line(image, corners[i], corners[(i + 1) % 4], (0, 255, 255), 2)
        # 标注四个角点
        labels = ["BL(0,0)", "BR", "TR", "TL"]
        for i, (corner, label) in enumerate(zip(corners, labels)):
            cv2.circle(image, corner, 5, (0, 255, 255), -1)
            cv2.putText(image, label, (corner[0] + 8, corner[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    # 绘制检测框和标注
    for item in result.detections:
        color = COLORS[item.class_id]
        x1, y1, x2, y2 = (round(v) for v in item.bbox_xyxy)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        cv2.circle(image, (round(item.center_x), round(item.center_y)), 4, color, -1)
        label = f"{item.class_name} {item.confidence:.2f} ({item.center_x:.0f},{item.center_y:.0f})"
        cv2.putText(image, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        if calibration is not None:
            x_mm, y_mm = calibration.to_mm(item.center_x, item.center_y)
            _, top_mm = calibration.to_mm(item.center_x, item.bbox_xyxy[1])
            _, bottom_mm = calibration.to_mm(item.center_x, item.bbox_xyxy[3])
            # 显示中心 X、Y 和上下边界 Y 坐标
            cv2.putText(image, f"X={x_mm:.1f} Y={y_mm:.1f}", (x1, min(image.shape[0] - 6, y2 + 18)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            if item.class_name == "Cube":
                cv2.putText(image, f"top Y={top_mm:.1f} bot Y={bottom_mm:.1f}",
                            (x1, min(image.shape[0] - 26, y2 + 38)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    cv2.putText(image, f"FPS {fps:.1f} | {device} | Q quit", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return image
