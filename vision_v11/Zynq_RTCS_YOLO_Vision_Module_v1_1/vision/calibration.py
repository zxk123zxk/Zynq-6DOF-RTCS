"""
视觉标定模块 - 基于四角圆形标记点的标定板定位
用于机器人抓取的坐标系标定
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass


@dataclass
class CircleMarker:
    """圆形标记点"""
    center: Tuple[float, float]  # 中心坐标 (x, y)
    radius: float  # 半径
    area: float  # 面积


@dataclass
class CalibrationResult:
    """标定结果"""
    corners: List[Tuple[float, float]]  # 四个角点坐标 [左上, 右上, 右下, 左下]
    center: Tuple[float, float]  # 标定板中心
    rotation_angle: float  # 旋转角度(度)
    transformation_matrix: np.ndarray  # 2D变换矩阵
    pixel_to_mm_ratio: Optional[float] = None  # 像素到毫米的比例


class CircleCalibration:
    """基于圆形标记点的视觉标定"""

    def __init__(self,
                 min_radius: int = 10,
                 max_radius: int = 100,
                 min_circularity: float = 0.7,
                 expected_marker_count: int = 4):
        """
        初始化标定器

        Args:
            min_radius: 最小圆半径(像素)
            max_radius: 最大圆半径(像素)
            min_circularity: 最小圆度(0-1)
            expected_marker_count: 期望的标记点数量
        """
        self.min_radius = min_radius
        self.max_radius = max_radius
        self.min_circularity = min_circularity
        self.expected_marker_count = expected_marker_count

    def detect_circles(self, image: np.ndarray) -> List[CircleMarker]:
        """
        检测图像中的圆形标记点

        Args:
            image: 输入图像(BGR或灰度)

        Returns:
            检测到的圆形标记点列表
        """
        # 转换为灰度图
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # 自适应二值化
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2
        )

        # 形态学操作去噪
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        # 查找轮廓
        contours, _ = cv2.findContours(
            binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        markers = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < np.pi * self.min_radius**2:
                continue
            if area > np.pi * self.max_radius**2:
                continue

            # 计算圆度
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter ** 2)

            if circularity < self.min_circularity:
                continue

            # 计算最小外接圆
            (x, y), radius = cv2.minEnclosingCircle(contour)

            # 验证半径范围
            if self.min_radius <= radius <= self.max_radius:
                markers.append(CircleMarker(
                    center=(float(x), float(y)),
                    radius=float(radius),
                    area=float(area)
                ))

        return markers

    def sort_corners(self, markers: List[CircleMarker]) -> List[Tuple[float, float]]:
        """
        将四个标记点按顺序排列: [左上, 右上, 右下, 左下]

        Args:
            markers: 检测到的标记点列表

        Returns:
            排序后的四个角点坐标
        """
        if len(markers) != 4:
            raise ValueError(f"需要4个标记点，但检测到{len(markers)}个")

        # 提取中心点
        points = np.array([m.center for m in markers])

        # 计算质心
        centroid = np.mean(points, axis=0)

        # 按照相对于质心的角度排序
        angles = np.arctan2(points[:, 1] - centroid[1],
                           points[:, 0] - centroid[0])

        # 从左上角开始(角度约为-3π/4)，逆时针排列
        # 调整角度使左上角为起点
        angles = (angles + np.pi * 5/4) % (2 * np.pi)
        sorted_indices = np.argsort(angles)

        sorted_points = points[sorted_indices]

        return [(float(p[0]), float(p[1])) for p in sorted_points]

    def calculate_transformation(self,
                                corners: List[Tuple[float, float]],
                                physical_size: Optional[Tuple[float, float]] = None
                                ) -> CalibrationResult:
        """
        计算标定变换矩阵

        Args:
            corners: 四个角点坐标 [左上, 右上, 右下, 左下]
            physical_size: 标定板实际尺寸(宽, 高)，单位毫米

        Returns:
            标定结果
        """
        corners_array = np.array(corners, dtype=np.float32)

        # 计算中心点
        center = tuple(np.mean(corners_array, axis=0))

        # 计算旋转角度(基于上边缘)
        top_left, top_right = corners_array[0], corners_array[1]
        dx = top_right[0] - top_left[0]
        dy = top_right[1] - top_left[1]
        rotation_angle = np.degrees(np.arctan2(dy, dx))

        # 计算像素到毫米的比例
        pixel_to_mm_ratio = None
        if physical_size is not None:
            # 计算图像中的宽度和高度
            width_pixels = np.linalg.norm(corners_array[1] - corners_array[0])
            height_pixels = np.linalg.norm(corners_array[3] - corners_array[0])

            # 平均比例
            width_ratio = physical_size[0] / width_pixels
            height_ratio = physical_size[1] / height_pixels
            pixel_to_mm_ratio = (width_ratio + height_ratio) / 2

        # 构建标准矩形(用于透视变换)
        if physical_size is not None:
            width, height = physical_size
        else:
            width = np.linalg.norm(corners_array[1] - corners_array[0])
            height = np.linalg.norm(corners_array[3] - corners_array[0])

        dst_points = np.array([
            [0, 0],
            [width, 0],
            [width, height],
            [0, height]
        ], dtype=np.float32)

        # 计算透视变换矩阵
        transformation_matrix = cv2.getPerspectiveTransform(
            corners_array, dst_points
        )

        return CalibrationResult(
            corners=corners,
            center=center,
            rotation_angle=rotation_angle,
            transformation_matrix=transformation_matrix,
            pixel_to_mm_ratio=pixel_to_mm_ratio
        )

    def calibrate(self,
                  image: np.ndarray,
                  physical_size: Optional[Tuple[float, float]] = None
                  ) -> Optional[CalibrationResult]:
        """
        执行完整的标定流程

        Args:
            image: 输入图像
            physical_size: 标定板实际尺寸(宽, 高)，单位毫米

        Returns:
            标定结果，如果失败返回None
        """
        # 检测圆形标记点
        markers = self.detect_circles(image)

        if len(markers) != self.expected_marker_count:
            print(f"警告: 期望检测{self.expected_marker_count}个标记点，"
                  f"实际检测到{len(markers)}个")
            return None

        # 排序角点
        try:
            corners = self.sort_corners(markers)
        except ValueError as e:
            print(f"错误: {e}")
            return None

        # 计算变换
        result = self.calculate_transformation(corners, physical_size)

        return result

    def transform_point(self,
                       point: Tuple[float, float],
                       calibration: CalibrationResult) -> Tuple[float, float]:
        """
        将图像坐标转换到标定板坐标系

        Args:
            point: 图像中的点坐标(x, y)
            calibration: 标定结果

        Returns:
            标定板坐标系中的点(x, y)
        """
        pt = np.array([[point]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(
            pt, calibration.transformation_matrix
        )
        return (float(transformed[0, 0, 0]), float(transformed[0, 0, 1]))

    def visualize(self,
                  image: np.ndarray,
                  calibration: CalibrationResult,
                  show_axes: bool = True) -> np.ndarray:
        """
        可视化标定结果

        Args:
            image: 输入图像
            calibration: 标定结果
            show_axes: 是否显示坐标轴

        Returns:
            标注后的图像
        """
        vis_image = image.copy()

        # 绘制角点
        colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 0)]
        labels = ['TL', 'TR', 'BR', 'BL']

        for i, (corner, color, label) in enumerate(zip(
            calibration.corners, colors, labels
        )):
            pt = (int(corner[0]), int(corner[1]))
            cv2.circle(vis_image, pt, 8, color, -1)
            cv2.putText(vis_image, label,
                       (pt[0] + 10, pt[1] - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # 绘制边界
        corners_int = np.array(calibration.corners, dtype=np.int32)
        cv2.polylines(vis_image, [corners_int], True, (0, 255, 255), 2)

        # 绘制中心点
        center_pt = (int(calibration.center[0]), int(calibration.center[1]))
        cv2.circle(vis_image, center_pt, 5, (255, 0, 255), -1)
        cv2.putText(vis_image, 'Center',
                   (center_pt[0] + 10, center_pt[1]),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)

        # 绘制坐标轴
        if show_axes:
            axis_length = 50
            angle_rad = np.radians(calibration.rotation_angle)

            # X轴(红色)
            x_end = (
                int(center_pt[0] + axis_length * np.cos(angle_rad)),
                int(center_pt[1] + axis_length * np.sin(angle_rad))
            )
            cv2.arrowedLine(vis_image, center_pt, x_end, (0, 0, 255), 2, tipLength=0.3)
            cv2.putText(vis_image, 'X', x_end,
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            # Y轴(绿色)
            y_end = (
                int(center_pt[0] - axis_length * np.sin(angle_rad)),
                int(center_pt[1] + axis_length * np.cos(angle_rad))
            )
            cv2.arrowedLine(vis_image, center_pt, y_end, (0, 255, 0), 2, tipLength=0.3)
            cv2.putText(vis_image, 'Y', y_end,
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # 显示旋转角度
        text = f"Angle: {calibration.rotation_angle:.2f}deg"
        cv2.putText(vis_image, text, (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if calibration.pixel_to_mm_ratio is not None:
            text = f"Ratio: {calibration.pixel_to_mm_ratio:.4f} mm/px"
            cv2.putText(vis_image, text, (10, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        return vis_image
