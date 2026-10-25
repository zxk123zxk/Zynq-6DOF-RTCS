"""
标定调试脚本 - 显示检测过程的每一步
"""

import cv2
import numpy as np
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from vision.calibration import CircleCalibration


def debug_circle_detection(image_path: str):
    """调试圆形检测过程"""

    # 读取图像
    image = cv2.imread(image_path)
    if image is None:
        print(f"错误: 无法读取图像 {image_path}")
        return

    print(f"图像尺寸: {image.shape[1]}x{image.shape[0]}")

    # 转换为灰度图
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 显示原图和灰度图
    cv2.imshow('1. Original', cv2.resize(image, (960, 540)))
    cv2.imshow('2. Grayscale', cv2.resize(gray, (960, 540)))

    # 尝试不同的二值化方法
    # 方法1: 自适应阈值
    binary1 = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 11, 2
    )
    cv2.imshow('3. Adaptive Threshold (INV)', cv2.resize(binary1, (960, 540)))

    # 方法2: 普通阈值
    _, binary2 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cv2.imshow('4. Otsu Threshold (INV)', cv2.resize(binary2, (960, 540)))

    # 方法3: 正向阈值
    binary3 = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    cv2.imshow('5. Adaptive Threshold', cv2.resize(binary3, (960, 540)))

    # 形态学操作
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary_clean = cv2.morphologyEx(binary1, cv2.MORPH_OPEN, kernel)
    binary_clean = cv2.morphologyEx(binary_clean, cv2.MORPH_CLOSE, kernel)
    cv2.imshow('6. After Morphology', cv2.resize(binary_clean, (960, 540)))

    # 查找轮廓
    contours, _ = cv2.findContours(
        binary_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    print(f"\n检测到 {len(contours)} 个轮廓")

    # 绘制所有轮廓
    contour_image = image.copy()
    cv2.drawContours(contour_image, contours, -1, (0, 255, 0), 2)
    cv2.imshow('7. All Contours', cv2.resize(contour_image, (960, 540)))

    # 分析每个轮廓
    valid_circles = []
    result_image = image.copy()

    for i, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if area < 100:  # 过滤太小的
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter == 0:
            continue

        circularity = 4 * np.pi * area / (perimeter ** 2)

        # 计算最小外接圆
        (x, y), radius = cv2.minEnclosingCircle(contour)

        print(f"\n轮廓 {i}:")
        print(f"  面积: {area:.2f}")
        print(f"  周长: {perimeter:.2f}")
        print(f"  圆度: {circularity:.3f}")
        print(f"  中心: ({x:.1f}, {y:.1f})")
        print(f"  半径: {radius:.1f}")

        # 绘制轮廓信息
        cv2.circle(result_image, (int(x), int(y)), int(radius), (0, 255, 255), 2)
        cv2.circle(result_image, (int(x), int(y)), 3, (0, 0, 255), -1)

        # 标注圆度
        text = f"{circularity:.2f}"
        cv2.putText(result_image, text, (int(x-20), int(y-radius-10)),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

        if circularity > 0.65 and 15 <= radius <= 80:
            valid_circles.append((x, y, radius, circularity))
            cv2.circle(result_image, (int(x), int(y)), int(radius), (0, 255, 0), 3)

    print(f"\n找到 {len(valid_circles)} 个有效圆形")

    cv2.imshow('8. Detected Circles', cv2.resize(result_image, (960, 540)))

    print("\n按任意键关闭...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        debug_circle_detection(sys.argv[1])
    else:
        print("用法: python debug_calibration.py <image_path>")
