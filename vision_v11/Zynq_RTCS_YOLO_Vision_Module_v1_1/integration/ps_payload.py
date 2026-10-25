"""将视觉结果转换为 JSON 兼容结构，不发送 Zynq 指令。"""
from __future__ import annotations

from vision.plane_calibration import PlaneCalibration
from vision.results import FrameResult


def to_ps_payload(result: FrameResult, calibration: PlaneCalibration | None = None) -> dict:
    """每帧零到多个目标；坐标为原始图像像素，给出标定时另附工作平面毫米坐标。

    对 Cube（正方体），额外输出 bbox 四边的毫米坐标，用于机械臂抓取规划。
    """
    detections = []
    for d in result.detections:
        x1, y1, x2, y2 = d.bbox_xyxy
        item = {"class_id": d.class_id, "class_name": d.class_name,
                "confidence": d.confidence, "bbox_xyxy": list(d.bbox_xyxy),
                "center_x": d.center_x, "center_y": d.center_y,
                "frame_width": result.frame_width, "frame_height": result.frame_height}
        if calibration is not None:
            item["center_x_mm"], item["center_y_mm"] = calibration.to_mm(d.center_x, d.center_y)
            # 输出 bbox 四边的毫米坐标（left/right/top/bottom）
            left_mm, _ = calibration.to_mm(x1, d.center_y)
            right_mm, _ = calibration.to_mm(x2, d.center_y)
            _, top_mm = calibration.to_mm(d.center_x, y1)
            _, bottom_mm = calibration.to_mm(d.center_x, y2)
            item["bbox_mm"] = {
                "left": left_mm, "right": right_mm,
                "top": top_mm, "bottom": bottom_mm,
                "width": abs(right_mm - left_mm),
                "height": abs(bottom_mm - top_mm)
            }
        detections.append(item)
    return {"frame_width": result.frame_width, "frame_height": result.frame_height,
            "detections": detections}
