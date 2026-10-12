"""Shared pixel-space output types for YOLO and OpenCV experiments."""
# SPDX-License-Identifier: AGPL-3.0-only
# 职责：定义 YOLO 与 OpenCV 共用的多目标、原图像素空间结果契约。
# 本模块不包含 Workspace 毫米坐标；真实标定前不得从这些像素字段推断物理位置。

from __future__ import annotations

from dataclasses import asdict, dataclass
import math


CLASS_NAMES = {0: "cube", 1: "cylinder"}


@dataclass(frozen=True)
class ObjectDetection:
    """One independent object detection in the original image coordinate frame.

    Coordinates use a top-left origin: x/u increases right and y/v increases
    down. bbox uses ``(x1, y1, x2, y2)`` in pixels and center uses ``(u, v)``.
    ``confidence`` is a model probability-like score for YOLO, but only a
    configurable geometric-fit score for the OpenCV detector; the two scores
    should not be compared as calibrated probabilities. Invalid candidates are
    represented by omission from the frame, not by stale or placeholder points.
    """

    class_id: int
    class_name: str
    confidence: float
    bbox_xyxy_px: tuple[float, float, float, float]
    center_px: tuple[float, float]
    timestamp_s: float | None
    valid: bool

    def __post_init__(self) -> None:
        if self.class_id not in CLASS_NAMES:
            raise ValueError(f"class_id must be one of {sorted(CLASS_NAMES)}")
        if self.class_name != CLASS_NAMES[self.class_id]:
            raise ValueError("class_name does not match class_id")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be finite and in [0, 1]")
        if self.timestamp_s is not None and not math.isfinite(self.timestamp_s):
            raise ValueError("timestamp_s must be finite or None")
        if len(self.bbox_xyxy_px) != 4 or not all(math.isfinite(value) for value in self.bbox_xyxy_px):
            raise ValueError("bbox_xyxy_px must contain four finite values")
        x1, y1, x2, y2 = self.bbox_xyxy_px
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bbox_xyxy_px must have positive width and height")
        if len(self.center_px) != 2 or not all(math.isfinite(value) for value in self.center_px):
            raise ValueError("center_px must contain two finite values")
        if not self.valid:
            raise ValueError("invalid candidates must not be exported as ObjectDetection")

    def to_dict(self) -> dict[str, object]:
        """转换为字典；tuple 结构和像素单位保持不变。"""
        return asdict(self)


@dataclass(frozen=True)
class ObjectDetectionFrame:
    """一帧中全部有效且相互独立的目标。

    ``frame_index`` 从输入源约定的首帧开始递增。``timestamp_s`` 可为 ``None``，
    具体来源必须由非空 ``timestamp_kind`` 标明。``detections=()`` 是合法空检测，
    不代表沿用上一帧目标。图像宽高和所有 bbox 都以原图像素为单位。
    """

    frame_index: int
    timestamp_s: float | None
    timestamp_kind: str
    image_width_px: int
    image_height_px: int
    detections: tuple[ObjectDetection, ...]

    def __post_init__(self) -> None:
        if self.frame_index < 0:
            raise ValueError("frame_index must be non-negative")
        if self.timestamp_s is not None and not math.isfinite(self.timestamp_s):
            raise ValueError("timestamp_s must be finite or None")
        if not self.timestamp_kind:
            raise ValueError("timestamp_kind must be explicit")
        if self.image_width_px <= 0 or self.image_height_px <= 0:
            raise ValueError("image dimensions must be positive")
        for detection in self.detections:
            x1, y1, x2, y2 = detection.bbox_xyxy_px
            if x1 < 0 or y1 < 0 or x2 > self.image_width_px or y2 > self.image_height_px:
                raise ValueError("detection bbox must stay inside the original image")
            if detection.timestamp_s != self.timestamp_s:
                raise ValueError("detection timestamp must match its frame timestamp")

    def to_dict(self) -> dict[str, object]:
        """转换为适合 JSON 序列化的嵌套字典。"""
        return asdict(self)
