"""Independent cube/cylinder detection and pixel-localization experiment."""
# SPDX-License-Identifier: AGPL-3.0-only

from .detection_types import ObjectDetection, ObjectDetectionFrame
from .opencv_geometry_detector import (
    BackgroundDifferenceMaskConfig,
    GeometryClassifierConfig,
    OpenCVGeometryDetector,
)
from .yolo_baseline_adapter import adapt_yolo_record

__all__ = [
    "BackgroundDifferenceMaskConfig",
    "GeometryClassifierConfig",
    "ObjectDetection",
    "ObjectDetectionFrame",
    "OpenCVGeometryDetector",
    "adapt_yolo_record",
]
