"""
标定演示程序
演示如何使用四角圆形标记点进行视觉标定
"""

import cv2
import numpy as np
import argparse
from pathlib import Path
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from vision.calibration import CircleCalibration, CalibrationResult


def calibrate_from_image(image_path: str,
                         physical_width: float = None,
                         physical_height: float = None,
                         save_result: bool = True):
    """
    从图像文件进行标定

    Args:
        image_path: 图像文件路径
        physical_width: 标定板实际宽度(毫米)
        physical_height: 标定板实际高度(毫米)
        save_result: 是否保存可视化结果
    """
    # 读取图像
    image = cv2.imread(image_path)
    if image is None:
        print(f"错误: 无法读取图像 {image_path}")
        return None

    print(f"图像尺寸: {image.shape[1]}x{image.shape[0]}")

    # 创建标定器
    calibrator = CircleCalibration(
        min_radius=15,
        max_radius=80,
        min_circularity=0.65,
        expected_marker_count=4
    )

    # 物理尺寸
    physical_size = None
    if physical_width and physical_height:
        physical_size = (physical_width, physical_height)
        print(f"标定板实际尺寸: {physical_width}mm x {physical_height}mm")

    # 执行标定
    print("\n开始标定...")
    result = calibrator.calibrate(image, physical_size)

    if result is None:
        print("标定失败!")
        return None

    # 打印结果
    print("\n=== 标定结果 ===")
    print(f"中心坐标: ({result.center[0]:.2f}, {result.center[1]:.2f})")
    print(f"旋转角度: {result.rotation_angle:.2f}°")

    print("\n四角坐标:")
    corner_names = ['左上', '右上', '右下', '左下']
    for name, corner in zip(corner_names, result.corners):
        print(f"  {name}: ({corner[0]:.2f}, {corner[1]:.2f})")

    if result.pixel_to_mm_ratio:
        print(f"\n像素到毫米比例: {result.pixel_to_mm_ratio:.4f} mm/px")

    # 可视化
    vis_image = calibrator.visualize(image, result, show_axes=True)

    # 显示
    cv2.imshow('Calibration Result', vis_image)
    print("\n按任意键继续...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    # 保存结果
    if save_result:
        output_path = Path(image_path).stem + '_calibrated.jpg'
        cv2.imwrite(output_path, vis_image)
        print(f"\n结果已保存到: {output_path}")

    return result


def calibrate_from_camera(camera_id: int = 0,
                          physical_width: float = None,
                          physical_height: float = None):
    """
    从相机实时标定

    Args:
        camera_id: 相机ID
        physical_width: 标定板实际宽度(毫米)
        physical_height: 标定板实际高度(毫米)
    """
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        print(f"错误: 无法打开相机 {camera_id}")
        return

    # 创建标定器
    calibrator = CircleCalibration(
        min_radius=15,
        max_radius=80,
        min_circularity=0.65,
        expected_marker_count=4
    )

    physical_size = None
    if physical_width and physical_height:
        physical_size = (physical_width, physical_height)

    print("相机已打开")
    print("按 's' 保存当前帧标定结果")
    print("按 'c' 执行标定")
    print("按 'q' 退出")

    calibration_result = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        display_frame = frame.copy()

        # 如果已有标定结果,显示坐标系
        if calibration_result:
            display_frame = calibrator.visualize(
                frame, calibration_result, show_axes=True
            )

        cv2.imshow('Camera Calibration', display_frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('c'):
            # 执行标定
            print("\n执行标定...")
            calibration_result = calibrator.calibrate(frame, physical_size)

            if calibration_result:
                print("标定成功!")
                print(f"中心: ({calibration_result.center[0]:.2f}, "
                      f"{calibration_result.center[1]:.2f})")
                print(f"角度: {calibration_result.rotation_angle:.2f}°")
            else:
                print("标定失败!")

        elif key == ord('s'):
            if calibration_result:
                # 保存结果
                output_path = f'calibration_result_{cv2.getTickCount()}.jpg'
                vis_frame = calibrator.visualize(
                    frame, calibration_result, show_axes=True
                )
                cv2.imwrite(output_path, vis_frame)
                print(f"已保存到: {output_path}")
            else:
                print("请先执行标定(按'c')")

    cap.release()
    cv2.destroyAllWindows()


def test_coordinate_transformation(calibration: CalibrationResult):
    """
    测试坐标变换功能

    Args:
        calibration: 标定结果
    """
    print("\n=== 坐标变换测试 ===")

    calibrator = CircleCalibration()

    # 测试几个点
    test_points = [
        calibration.center,
        calibration.corners[0],
        calibration.corners[1],
        calibration.corners[2],
        calibration.corners[3],
    ]

    point_names = ['中心', '左上角', '右上角', '右下角', '左下角']

    for name, point in zip(point_names, test_points):
        transformed = calibrator.transform_point(point, calibration)
        print(f"{name}: 图像({point[0]:.2f}, {point[1]:.2f}) -> "
              f"标定板({transformed[0]:.2f}, {transformed[1]:.2f})")


def main():
    parser = argparse.ArgumentParser(
        description='视觉标定演示程序'
    )
    parser.add_argument(
        '--mode',
        choices=['image', 'camera'],
        default='image',
        help='标定模式: image(图像文件) 或 camera(实时相机)'
    )
    parser.add_argument(
        '--input',
        type=str,
        help='输入图像路径(image模式)'
    )
    parser.add_argument(
        '--camera',
        type=int,
        default=0,
        help='相机ID(camera模式)'
    )
    parser.add_argument(
        '--width',
        type=float,
        help='标定板实际宽度(毫米)'
    )
    parser.add_argument(
        '--height',
        type=float,
        help='标定板实际高度(毫米)'
    )
    parser.add_argument(
        '--no-save',
        action='store_true',
        help='不保存结果'
    )

    args = parser.parse_args()

    if args.mode == 'image':
        if not args.input:
            print("错误: image模式需要指定 --input 参数")
            return

        result = calibrate_from_image(
            args.input,
            args.width,
            args.height,
            not args.no_save
        )

        if result:
            test_coordinate_transformation(result)

    else:  # camera
        calibrate_from_camera(
            args.camera,
            args.width,
            args.height
        )


if __name__ == '__main__':
    main()
