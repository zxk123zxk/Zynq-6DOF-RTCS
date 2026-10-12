"""Adapt frozen experiment-A JSON records to the shared multi-object output."""
# SPDX-License-Identifier: AGPL-3.0-only
# 职责：把既有 YOLO A 记录转换为统一的原图像素多目标接口，不重新运行或修改模型。

from __future__ import annotations

import math
from typing import Mapping

from .detection_types import CLASS_NAMES, ObjectDetection, ObjectDetectionFrame


def adapt_yolo_record(record: Mapping[str, object], *, minimum_confidence: float = 0.25) -> ObjectDetectionFrame:
    """转换一条 YOLO A 帧记录。

    仅保留类别 0/1 且 ``confidence >= minimum_confidence`` 的检测。输入 bbox 使用
    ``bbox_xyxy`` 原图像素坐标，输出中心由 bbox 计算。低置信度或未知类别被省略；
    没有保留目标时输出合法空列表，不生成旧坐标。缺失必需字段会按现有字典访问
    语义抛出异常。
    """
    if not 0 <= minimum_confidence <= 1:
        raise ValueError("minimum_confidence must be in [0, 1]")
    timestamp = record.get("timestamp_s")
    timestamp_s = None if timestamp is None else float(timestamp)
    detections: list[ObjectDetection] = []
    for raw_object in record.get("detections", []):
        raw = dict(raw_object)
        class_id = int(raw["class_id"])
        confidence = float(raw["confidence"])
        if class_id not in CLASS_NAMES or confidence < minimum_confidence:
            continue
        box = tuple(float(value) for value in raw["bbox_xyxy"])
        x1, y1, x2, y2 = box
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        detections.append(
            ObjectDetection(
                class_id=class_id,
                class_name=CLASS_NAMES[class_id],
                confidence=confidence,
                bbox_xyxy_px=box,
                center_px=center,
                timestamp_s=timestamp_s,
                valid=True,
            )
        )
    detections.sort(key=lambda item: (item.center_px[0], item.center_px[1]))
    return ObjectDetectionFrame(
        frame_index=int(record["frame_index"]),
        timestamp_s=timestamp_s,
        timestamp_kind=str(record.get("timestamp_kind", "unspecified")),
        image_width_px=int(record["image_width_px"]),
        image_height_px=int(record["image_height_px"]),
        detections=tuple(detections),
    )
