"""将视觉结果转换为 JSON 兼容结构，不发送 Zynq 指令。"""
from __future__ import annotations

from vision.results import FrameResult


def to_ps_payload(result: FrameResult) -> dict:
    """每帧零到多个目标；所有坐标为原始图像像素。"""
    return {"frame_width": result.frame_width, "frame_height": result.frame_height,
            "detections": [{"class_id": d.class_id, "class_name": d.class_name,
                            "confidence": d.confidence, "bbox_xyxy": list(d.bbox_xyxy),
                            "center_x": d.center_x, "center_y": d.center_y,
                            "frame_width": result.frame_width, "frame_height": result.frame_height}
                           for d in result.detections]}
