"""
手动标注四角点的标定程序 - 修复版
支持鼠标点击标注四个角点,然后进行标定
修复了中文乱码和窗口超出屏幕的问题
"""

import cv2
import numpy as np
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from vision.calibration import CalibrationResult


class ManualCalibration:
    """手动标注标定"""

    def __init__(self, image_path: str, max_display_width=1280, max_display_height=720):
        self.image_path = image_path
        # 使用numpy读取以支持中文路径
        try:
            self.image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        except:
            self.image = None
        if self.image is None:
            raise ValueError(f"Cannot read image: {image_path}")

        # 计算缩放比例以适应屏幕
        h, w = self.image.shape[:2]
        self.scale = 1.0

        if w > max_display_width or h > max_display_height:
            scale_w = max_display_width / w
            scale_h = max_display_height / h
            self.scale = min(scale_w, scale_h)
            new_w = int(w * self.scale)
            new_h = int(h * self.scale)
            self.display_size = (new_w, new_h)
            print(f"Original size: {w}x{h}, Scale: {self.scale:.3f}, Display size: {new_w}x{new_h}")
        else:
            self.display_size = (w, h)
            print(f"Image size: {w}x{h}, No scaling needed")

        self.display_image = self.image.copy()
        self.points = []  # 存储在原始图像坐标系中
        self.window_name = 'Manual Calibration - Click: TL, TR, BR, BL'

    def mouse_callback(self, event, x, y, flags, param):
        """鼠标回调函数"""
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(self.points) < 4:
                # 将显示坐标转换回原始图像坐标
                orig_x = int(x / self.scale)
                orig_y = int(y / self.scale)
                self.points.append((orig_x, orig_y))
                print(f"Point {len(self.points)}: ({orig_x}, {orig_y})")

                # 绘制点
                colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 0)]
                labels = ['TL', 'TR', 'BR', 'BL']

                self.display_image = self.image.copy()

                # 绘制已标注的点
                for i, (pt, color, label) in enumerate(zip(self.points, colors, labels)):
                    cv2.circle(self.display_image, pt, 8, color, -1)
                    cv2.putText(self.display_image, label,
                               (pt[0] + 15, pt[1] - 15),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

                # 如果标注了至少2个点,绘制连线
                if len(self.points) >= 2:
                    pts = np.array(self.points, dtype=np.int32)
                    cv2.polylines(self.display_image, [pts], False, (0, 255, 255), 2)

                # 如果标注了4个点,闭合多边形
                if len(self.points) == 4:
                    pts = np.array(self.points, dtype=np.int32)
                    cv2.polylines(self.display_image, [pts], True, (0, 255, 255), 3)

                    # 计算中心
                    center = np.mean(pts, axis=0).astype(int)
                    cv2.circle(self.display_image, tuple(center), 5, (255, 0, 255), -1)
                    cv2.putText(self.display_image, 'Center',
                               (center[0] + 10, center[1]),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 2)

                    print("\nAll 4 corners marked. Press 'Enter' to confirm, 'r' to reset")

                # 缩放显示图像
                display_scaled = cv2.resize(self.display_image, self.display_size)
                cv2.imshow(self.window_name, display_scaled)

    def annotate(self):
        """交互式标注"""
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, self.display_size[0], self.display_size[1])
        cv2.setMouseCallback(self.window_name, self.mouse_callback)

        # 显示提示信息
        info_image = self.image.copy()
        cv2.putText(info_image, "Please click 4 corners in order:",
                   (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(info_image, "1. Top-Left (red)",
                   (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.putText(info_image, "2. Top-Right (green)",
                   (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(info_image, "3. Bottom-Right (blue)",
                   (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
        cv2.putText(info_image, "4. Bottom-Left (yellow)",
                   (20, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(info_image, "Press 'r' to reset, 'q' to quit",
                   (20, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        # 缩放显示
        info_image_scaled = cv2.resize(info_image, self.display_size)
        cv2.imshow(self.window_name, info_image_scaled)

        print("\n=== Manual Calibration ===")
        print("Click 4 corners in order: Top-Left -> Top-Right -> Bottom-Right -> Bottom-Left")
        print("Press 'r' to reset, 'q' to quit\n")

        while True:
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q'):
                print("Calibration cancelled")
                cv2.destroyAllWindows()
                return None

            elif key == ord('r'):
                # 重置
                print("\nResetting...")
                self.points = []
                self.display_image = self.image.copy()
                info_image_scaled = cv2.resize(info_image, self.display_size)
                cv2.imshow(self.window_name, info_image_scaled)

            elif key == 13:  # Enter
                if len(self.points) == 4:
                    print("\nCalibration confirmed!")
                    cv2.destroyAllWindows()
                    return self.points
                else:
                    print(f"Please mark 4 points (currently {len(self.points)} points marked)")

    def calculate_calibration(self, corners, physical_size=None):
        """计算标定结果"""
        corners_array = np.array(corners, dtype=np.float32)

        # 计算中心点
        center = tuple(np.mean(corners_array, axis=0))

        # 计算旋转角度
        top_left, top_right = corners_array[0], corners_array[1]
        dx = top_right[0] - top_left[0]
        dy = top_right[1] - top_left[1]
        rotation_angle = np.degrees(np.arctan2(dy, dx))

        # 计算像素到毫米的比例
        pixel_to_mm_ratio = None
        if physical_size is not None:
            width_pixels = np.linalg.norm(corners_array[1] - corners_array[0])
            height_pixels = np.linalg.norm(corners_array[3] - corners_array[0])
            width_ratio = physical_size[0] / width_pixels
            height_ratio = physical_size[1] / height_pixels
            pixel_to_mm_ratio = (width_ratio + height_ratio) / 2

        # 构建透视变换矩阵
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

        transformation_matrix = cv2.getPerspectiveTransform(corners_array, dst_points)

        return CalibrationResult(
            corners=corners,
            center=center,
            rotation_angle=rotation_angle,
            transformation_matrix=transformation_matrix,
            pixel_to_mm_ratio=pixel_to_mm_ratio
        )

    def visualize(self, calibration: CalibrationResult):
        """可视化标定结果"""
        vis_image = self.image.copy()

        # 绘制角点
        colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 0)]
        labels = ['TL', 'TR', 'BR', 'BL']

        for corner, color, label in zip(calibration.corners, colors, labels):
            pt = (int(corner[0]), int(corner[1]))
            cv2.circle(vis_image, pt, 8, color, -1)
            cv2.putText(vis_image, label,
                       (pt[0] + 15, pt[1] - 15),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        # 绘制边界
        corners_int = np.array(calibration.corners, dtype=np.int32)
        cv2.polylines(vis_image, [corners_int], True, (0, 255, 255), 3)

        # 绘制中心点
        center_pt = (int(calibration.center[0]), int(calibration.center[1]))
        cv2.circle(vis_image, center_pt, 8, (255, 0, 255), -1)
        cv2.putText(vis_image, 'Center',
                   (center_pt[0] + 15, center_pt[1]),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 2)

        # 绘制坐标轴
        axis_length = 100
        angle_rad = np.radians(calibration.rotation_angle)

        # X轴(红色)
        x_end = (
            int(center_pt[0] + axis_length * np.cos(angle_rad)),
            int(center_pt[1] + axis_length * np.sin(angle_rad))
        )
        cv2.arrowedLine(vis_image, center_pt, x_end, (0, 0, 255), 3, tipLength=0.3)
        cv2.putText(vis_image, 'X', x_end,
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        # Y轴(绿色)
        y_end = (
            int(center_pt[0] - axis_length * np.sin(angle_rad)),
            int(center_pt[1] + axis_length * np.cos(angle_rad))
        )
        cv2.arrowedLine(vis_image, center_pt, y_end, (0, 255, 0), 3, tipLength=0.3)
        cv2.putText(vis_image, 'Y', y_end,
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # 显示信息
        cv2.putText(vis_image, f"Rotation: {calibration.rotation_angle:.2f} deg",
                   (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        if calibration.pixel_to_mm_ratio is not None:
            cv2.putText(vis_image, f"Ratio: {calibration.pixel_to_mm_ratio:.4f} mm/px",
                       (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        return vis_image


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Manual corner calibration program')
    parser.add_argument('--input', type=str, required=True, help='Input image path')
    parser.add_argument('--width', type=float, help='Actual width of calibration board (mm)')
    parser.add_argument('--height', type=float, help='Actual height of calibration board (mm)')
    parser.add_argument('--output', type=str, help='Output calibration result image path')
    parser.add_argument('--max-width', type=int, default=1280, help='Max display width (default: 1280)')
    parser.add_argument('--max-height', type=int, default=720, help='Max display height (default: 720)')

    args = parser.parse_args()

    # 创建标定器
    calibrator = ManualCalibration(args.input, args.max_width, args.max_height)

    # 交互式标注
    corners = calibrator.annotate()

    if corners is None:
        print("Calibration cancelled")
        return

    # 物理尺寸
    physical_size = None
    if args.width and args.height:
        physical_size = (args.width, args.height)
        print(f"\nCalibration board actual size: {args.width} mm x {args.height} mm")

    # 计算标定
    result = calibrator.calculate_calibration(corners, physical_size)

    # 打印结果
    print("\n=== Calibration Result ===")
    print(f"Center: ({result.center[0]:.2f}, {result.center[1]:.2f})")
    print(f"Rotation: {result.rotation_angle:.2f} degrees")

    print("\nCorner coordinates:")
    corner_names = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left']
    for name, corner in zip(corner_names, result.corners):
        print(f"  {name}: ({corner[0]:.2f}, {corner[1]:.2f})")

    if result.pixel_to_mm_ratio:
        print(f"\nPixel to mm ratio: {result.pixel_to_mm_ratio:.4f} mm/px")

    # 计算标定板尺寸(像素)
    width_px = np.linalg.norm(np.array(result.corners[1]) - np.array(result.corners[0]))
    height_px = np.linalg.norm(np.array(result.corners[3]) - np.array(result.corners[0]))
    print(f"\nCalibration board size (pixels): {width_px:.2f} x {height_px:.2f}")

    # 可视化
    vis_image = calibrator.visualize(result)

    # 保存结果
    if args.output:
        output_path = args.output
    else:
        output_path = Path(args.input).stem + '_manual_calibrated.jpg'

    cv2.imwrite(output_path, vis_image)
    print(f"\nCalibration result saved to: {output_path}")

    # 显示结果（带缩放）
    vis_scaled = cv2.resize(vis_image, calibrator.display_size)
    cv2.namedWindow('Calibration Result', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Calibration Result', calibrator.display_size[0], calibrator.display_size[1])
    cv2.imshow('Calibration Result', vis_scaled)
    print("\nPress any key to close...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
