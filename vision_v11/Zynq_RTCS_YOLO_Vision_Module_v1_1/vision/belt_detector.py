"""实时检测传送带边界，自动计算坐标映射。"""
from __future__ import annotations

import cv2
import numpy as np


class BeltDetector:
    """基于颜色和轮廓检测传送带边界，动态计算坐标变换。"""

    def __init__(self, belt_width_mm: float = 490.0, belt_height_mm: float = 80.0):
        """
        Args:
            belt_width_mm: 传送带实际宽度（毫米）
            belt_height_mm: 传送带实际高度（毫米）
        """
        self.belt_width_mm = belt_width_mm
        self.belt_height_mm = belt_height_mm
        # HSV 绿色范围：宽松一些，适应不同光照
        self.hsv_lower = np.array([35, 50, 35])
        self.hsv_upper = np.array([90, 255, 200])
        self.corners_px = None
        self.matrix = None
        self.inv_matrix = None

    def detect(self, frame_bgr) -> bool:
        """检测当前帧中的传送带，更新角点和变换矩阵。返回是否检测成功。"""
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)

        # 形态学操作去噪并平滑边缘
        kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)

        # 额外的膨胀+腐蚀，平滑边界
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
        mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=2)

        # 找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False

        # 筛选候选轮廓：面积、长宽比、位置
        frame_h, frame_w = frame_bgr.shape[:2]
        candidates = []

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 15000:  # 降低面积要求
                continue

            # 计算最小外接矩形
            rect = cv2.minAreaRect(contour)
            (cx, cy), (w, h), angle = rect

            # 确保 w 是长边
            if w < h:
                w, h = h, w
                angle = (angle + 90) % 180

            # 长宽比约束：放宽到 3.5~12（传送带实际约 6.1）
            aspect_ratio = w / max(h, 1.0)
            if aspect_ratio < 3.5 or aspect_ratio > 12.0:
                continue

            # 位置约束：放宽到整个画面中下部
            if cy < frame_h * 0.2 or cy > frame_h * 0.95:
                continue

            # 计算评分：面积大、长宽比接近 6、靠近画面中央的优先
            target_ratio = self.belt_width_mm / self.belt_height_mm
            ratio_score = 1.0 / (1.0 + abs(aspect_ratio - target_ratio))
            area_score = min(area / 100000.0, 1.0)
            center_x_offset = abs(cx - frame_w / 2) / frame_w
            center_score = 1.0 - center_x_offset

            score = area_score * 0.4 + ratio_score * 0.4 + center_score * 0.2
            candidates.append((score, contour, rect))

        if not candidates:
            return False

        # 选择得分最高的轮廓
        candidates.sort(key=lambda x: x[0], reverse=True)
        _, best_contour, best_rect = candidates[0]

        # 使用旋转矩形的四个角点（更精确）
        box = cv2.boxPoints(best_rect)
        corners = np.array(box, dtype=np.float32)

        # 可选：用轮廓精确拟合来优化角点
        # 对轮廓进行多边形逼近
        epsilon = 0.01 * cv2.arcLength(best_contour, True)
        approx = cv2.approxPolyDP(best_contour, epsilon, True)

        # 如果多边形逼近得到 4 个点，用它替代旋转矩形
        if len(approx) == 4:
            corners = approx.reshape(4, 2).astype(np.float32)

        # 排序角点：左下、右下、右上、左上
        corners = self._sort_corners(corners)
        self.corners_px = corners

        # 计算透视变换矩阵：像素坐标 → 毫米坐标
        dst_corners = np.array([
            [0, 0],  # 左下角为原点
            [self.belt_width_mm, 0],  # 右下
            [self.belt_width_mm, self.belt_height_mm],  # 右上
            [0, self.belt_height_mm],  # 左上
        ], dtype=np.float32)

        self.matrix = cv2.getPerspectiveTransform(corners, dst_corners)
        self.inv_matrix = cv2.getPerspectiveTransform(dst_corners, corners)
        return True

    def _sort_corners(self, points: np.ndarray) -> np.ndarray:
        """将四个点排序为：左下、右下、右上、左上。"""
        # 按 Y 坐标排序，前两个是下方，后两个是上方
        points = points[points[:, 1].argsort()]
        bottom = points[:2]
        top = points[2:]

        # 下方两点按 X 排序：左下、右下
        bottom = bottom[bottom[:, 0].argsort()]
        # 上方两点按 X 排序：左上、右上，然后反转成右上、左上
        top = top[top[:, 0].argsort()][::-1]

        return np.array([bottom[0], bottom[1], top[0], top[1]], dtype=np.float32)

    def to_mm(self, x_px: float, y_px: float) -> tuple[float, float]:
        """像素坐标转毫米坐标。"""
        if self.matrix is None:
            raise RuntimeError("未检测到传送带，无法转换坐标")
        pt = np.array([[[x_px, y_px]]], dtype=np.float32)
        result = cv2.perspectiveTransform(pt, self.matrix)
        return float(result[0, 0, 0]), float(result[0, 0, 1])

    def to_px(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        """毫米坐标转像素坐标。"""
        if self.inv_matrix is None:
            raise RuntimeError("未检测到传送带，无法转换坐标")
        pt = np.array([[[x_mm, y_mm]]], dtype=np.float32)
        result = cv2.perspectiveTransform(pt, self.inv_matrix)
        return float(result[0, 0, 0]), float(result[0, 0, 1])

    def is_ready(self) -> bool:
        """是否已成功检测到传送带。"""
        return self.matrix is not None
