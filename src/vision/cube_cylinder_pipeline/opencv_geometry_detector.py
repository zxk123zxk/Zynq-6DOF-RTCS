"""Controlled-scene OpenCV contour and geometry detector.

This detector is intentionally limited to a fixed, near-top-down camera with a
uniform background, separated objects, cubes resting on a face, and cylinders
standing with their axes close to the camera optical axis.
"""
# SPDX-License-Identifier: AGPL-3.0-only
# 职责：在严格受控的固定近俯视场景中，通过背景差分和轮廓几何实验性地区分 cube/cylinder。
# 所有输出保持原图像素坐标；该模块不包含相机标定、毫米坐标或抓取控制。

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np

from .detection_types import ObjectDetection, ObjectDetectionFrame


@dataclass(frozen=True)
class BackgroundDifferenceMaskConfig:
    """固定背景颜色差分配置。

    ``background_bgr`` 为 0..255 的 BGR 三元组，``distance_threshold`` 为 BGR
    欧氏距离阈值，``morphology_kernel_px`` 为像素单位的奇数核尺寸。该简化模型
    只适合背景和光照稳定的受控场景。
    """

    background_bgr: tuple[int, int, int]
    distance_threshold: float
    morphology_kernel_px: int = 3

    def __post_init__(self) -> None:
        if len(self.background_bgr) != 3 or not all(0 <= value <= 255 for value in self.background_bgr):
            raise ValueError("background_bgr must contain three values in [0, 255]")
        if not math.isfinite(self.distance_threshold) or self.distance_threshold <= 0:
            raise ValueError("distance_threshold must be positive and finite")
        if self.morphology_kernel_px < 0 or (
            self.morphology_kernel_px not in (0, 1) and self.morphology_kernel_px % 2 == 0
        ):
            raise ValueError("morphology_kernel_px must be 0, 1, or a positive odd number")


@dataclass(frozen=True)
class GeometryClassifierConfig:
    """轮廓尺寸和几何分类阈值，面积单位 px²、边长单位 px。

    这些默认值来自实验性合成/受控测试，不代表最终 Camera 或任意姿态下的物理
    尺寸。cube 需近似方形顶视轮廓，cylinder 需立放并呈近圆形顶视轮廓。
    """

    min_area_px2: float = 300.0
    max_area_px2: float = 20000.0
    min_side_px: int = 12
    max_side_px: int = 180
    polygon_epsilon_fraction: float = 0.025
    max_rotated_aspect_ratio: float = 1.30
    cube_min_rectangularity: float = 0.82
    cylinder_min_circularity: float = 0.82
    min_geometry_confidence: float = 0.72

    def __post_init__(self) -> None:
        if not 0 <= self.min_area_px2 < self.max_area_px2:
            raise ValueError("area limits are invalid")
        if not 0 < self.min_side_px < self.max_side_px:
            raise ValueError("side limits are invalid")
        if not 0 < self.polygon_epsilon_fraction < 0.2:
            raise ValueError("polygon_epsilon_fraction is invalid")
        if self.max_rotated_aspect_ratio <= 1:
            raise ValueError("max_rotated_aspect_ratio must be greater than 1")
        for name, value in (
            ("cube_min_rectangularity", self.cube_min_rectangularity),
            ("cylinder_min_circularity", self.cylinder_min_circularity),
            ("min_geometry_confidence", self.min_geometry_confidence),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class ContourDiagnostic:
    """一个外轮廓的像素几何诊断；被拒绝的轮廓不会导出为目标。"""

    bbox_xyxy_px: tuple[int, int, int, int]
    area_px2: float
    perimeter_px: float
    circularity: float
    polygon_vertices: int
    rotated_aspect_ratio: float
    rectangularity: float
    accepted: bool
    rejection_reason: str | None


class OpenCVGeometryDetector:
    """分割统一背景中的物体，再按顶视轮廓分类。

    ``roi_xyxy_px`` 使用输入原图像素坐标 ``(x1,y1,x2,y2)``。检测结果会加回
    ROI 偏移，仍以原图左上角为原点。轮廓粘连、遮挡、倾倒 cylinder、非方形
    cube 视角或圆形干扰物均可能导致拒绝、漏检或误检。
    """

    def __init__(
        self,
        mask_config: BackgroundDifferenceMaskConfig,
        geometry_config: GeometryClassifierConfig | None = None,
        *,
        roi_xyxy_px: tuple[int, int, int, int] | None = None,
    ) -> None:
        """保存背景、几何阈值与可选 ROI，不读取 Camera 或背景图片。"""
        self.mask_config = mask_config
        self.geometry_config = geometry_config or GeometryClassifierConfig()
        self.roi_xyxy_px = roi_xyxy_px

    def _validate_roi(self, width: int, height: int) -> tuple[int, int, int, int]:
        """验证 ROI 完全位于输入图像内；未配置时返回整幅图像。"""
        if self.roi_xyxy_px is None:
            return 0, 0, width, height
        x1, y1, x2, y2 = self.roi_xyxy_px
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError("roi_xyxy_px must lie inside the input image")
        return x1, y1, x2, y2

    def foreground_mask(self, frame_bgr: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """生成 ROI 局部二值前景 Mask，并返回其原图 ROI。

        输入必须是非空三通道 BGR 数组。返回 Mask 的坐标原点位于 ROI 左上角，
        与最终 ``ObjectDetection`` 的原图像素坐标不同。
        """
        if frame_bgr is None or frame_bgr.size == 0 or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            raise ValueError("frame_bgr must be a non-empty BGR image")
        height, width = frame_bgr.shape[:2]
        roi = self._validate_roi(width, height)
        x1, y1, x2, y2 = roi
        crop = frame_bgr[y1:y2, x1:x2].astype(np.float32)
        background = np.asarray(self.mask_config.background_bgr, dtype=np.float32)
        distance = np.linalg.norm(crop - background, axis=2)
        mask = np.where(distance >= self.mask_config.distance_threshold, 255, 0).astype(np.uint8)
        kernel_size = self.mask_config.morphology_kernel_px
        if kernel_size > 1:
            kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        return mask, roi

    def detect(
        self,
        frame_bgr: np.ndarray,
        *,
        frame_index: int,
        timestamp_s: float | None,
        timestamp_kind: str,
    ) -> tuple[ObjectDetectionFrame, np.ndarray, tuple[ContourDiagnostic, ...]]:
        """检测一帧中的全部有效目标并返回 frame、ROI Mask 和轮廓诊断。

        ``timestamp_s`` 原样传播，其语义必须由调用方通过 ``timestamp_kind`` 指定。
        空检测以空元组表示；几何分数只是规则拟合分数，不是训练模型概率。
        """
        mask, (offset_x, offset_y, _, _) = self.foreground_mask(frame_bgr)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[ObjectDetection] = []
        diagnostics: list[ContourDiagnostic] = []
        for contour in contours:
            detection, diagnostic = self._classify_contour(
                contour, offset_x=offset_x, offset_y=offset_y, timestamp_s=timestamp_s
            )
            diagnostics.append(diagnostic)
            if detection is not None:
                detections.append(detection)
        detections.sort(key=lambda item: (item.center_px[0], item.center_px[1]))
        diagnostics.sort(key=lambda item: item.bbox_xyxy_px)
        height, width = frame_bgr.shape[:2]
        frame = ObjectDetectionFrame(
            frame_index=frame_index,
            timestamp_s=timestamp_s,
            timestamp_kind=timestamp_kind,
            image_width_px=width,
            image_height_px=height,
            detections=tuple(detections),
        )
        return frame, mask, tuple(diagnostics)

    def _classify_contour(
        self,
        contour: np.ndarray,
        *,
        offset_x: int,
        offset_y: int,
        timestamp_s: float | None,
    ) -> tuple[ObjectDetection | None, ContourDiagnostic]:
        """按冻结阈值分类单个 ROI 轮廓，并将 bbox/center 恢复到原图像素坐标。"""
        cfg = self.geometry_config
        area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, True))
        x, y, width, height = cv2.boundingRect(contour)
        global_box = (x + offset_x, y + offset_y, x + width + offset_x, y + height + offset_y)
        circularity = 4.0 * math.pi * area / (perimeter * perimeter) if perimeter > 0 else 0.0
        approx = cv2.approxPolyDP(contour, cfg.polygon_epsilon_fraction * perimeter, True)
        rect = cv2.minAreaRect(contour)
        rect_width, rect_height = rect[1]
        short_side, long_side = sorted((float(rect_width), float(rect_height)))
        rotated_aspect = long_side / short_side if short_side > 0 else math.inf
        rect_area = rect_width * rect_height
        rectangularity = area / rect_area if rect_area > 0 else 0.0

        reason: str | None = None
        if not cfg.min_area_px2 <= area <= cfg.max_area_px2:
            reason = "area_out_of_range"
        elif not cfg.min_side_px <= short_side and long_side <= cfg.max_side_px:
            reason = "size_out_of_range"
        elif rotated_aspect > cfg.max_rotated_aspect_ratio:
            reason = "not_near_square_or_circle"

        detection: ObjectDetection | None = None
        if reason is None:
            aspect_score = max(0.0, 1.0 - (rotated_aspect - 1.0) / (cfg.max_rotated_aspect_ratio - 1.0))
            cylinder_score = min(1.0, circularity) * aspect_score
            cube_score = min(1.0, rectangularity) * aspect_score if len(approx) == 4 else 0.0
            if circularity >= cfg.cylinder_min_circularity and cylinder_score >= cfg.min_geometry_confidence:
                class_id, confidence = 1, cylinder_score
            elif (
                len(approx) == 4
                and rectangularity >= cfg.cube_min_rectangularity
                and cube_score >= cfg.min_geometry_confidence
            ):
                class_id, confidence = 0, cube_score
            else:
                reason = "ambiguous_geometry"
                class_id, confidence = -1, 0.0

            if reason is None:
                moments = cv2.moments(contour)
                if moments["m00"] > 0:
                    center = (
                        float(moments["m10"] / moments["m00"] + offset_x),
                        float(moments["m01"] / moments["m00"] + offset_y),
                    )
                else:
                    center = (
                        float(global_box[0] + global_box[2]) / 2,
                        float(global_box[1] + global_box[3]) / 2,
                    )
                detection = ObjectDetection(
                    class_id=class_id,
                    class_name="cube" if class_id == 0 else "cylinder",
                    confidence=float(max(0.0, min(1.0, confidence))),
                    bbox_xyxy_px=tuple(float(value) for value in global_box),
                    center_px=center,
                    timestamp_s=timestamp_s,
                    valid=True,
                )

        diagnostic = ContourDiagnostic(
            bbox_xyxy_px=global_box,
            area_px2=area,
            perimeter_px=perimeter,
            circularity=circularity,
            polygon_vertices=len(approx),
            rotated_aspect_ratio=rotated_aspect,
            rectangularity=rectangularity,
            accepted=detection is not None,
            rejection_reason=reason,
        )
        return detection, diagnostic
