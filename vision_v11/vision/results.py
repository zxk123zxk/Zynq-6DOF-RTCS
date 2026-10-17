"""原始图像像素坐标的检测结果契约。"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


CLASS_NAMES = {0: "Cube", 1: "Cylinder"}


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]
    center_x: float
    center_y: float

    @classmethod
    def from_bbox(cls, class_id: int, confidence: float,
                  bbox_xyxy: tuple[float, float, float, float],
                  width: int, height: int) -> Detection:
        """裁到原始帧范围，并从框计算中心；坐标为浮点像素。"""
        if class_id not in CLASS_NAMES or not isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("类别或置信度无效")
        if width <= 0 or height <= 0 or len(bbox_xyxy) != 4 or not all(map(isfinite, bbox_xyxy)):
            raise ValueError("图像尺寸或 bbox 无效")
        x1, y1, x2, y2 = bbox_xyxy
        x1, x2 = max(0.0, min(x1, width)), max(0.0, min(x2, width))
        y1, y2 = max(0.0, min(y1, height)), max(0.0, min(y2, height))
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bbox 面积必须大于零")
        return cls(class_id, CLASS_NAMES[class_id], confidence, (x1, y1, x2, y2),
                   (x1 + x2) / 2, (y1 + y2) / 2)


@dataclass(frozen=True)
class FrameResult:
    """一帧的全部目标；无检测时 detections 为空元组。"""
    frame_width: int
    frame_height: int
    detections: tuple[Detection, ...]

    def __post_init__(self) -> None:
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ValueError("帧尺寸必须为正数")
