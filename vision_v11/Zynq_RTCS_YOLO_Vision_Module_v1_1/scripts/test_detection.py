"""
测试不同的圆形检测方法
"""

import cv2
import numpy as np
import sys
from pathlib import Path

def detect_circles_method1(image):
    """方法1: 霍夫圆检测"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (9, 9), 2)

    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=50,
        param1=50,
        param2=30,
        minRadius=10,
        maxRadius=100
    )

    result = image.copy()
    if circles is not None:
        circles = np.uint16(np.around(circles))
        print(f"方法1(霍夫圆): 检测到 {len(circles[0])} 个圆")
        for i in circles[0, :]:
            cv2.circle(result, (i[0], i[1]), i[2], (0, 255, 0), 2)
            cv2.circle(result, (i[0], i[1]), 2, (0, 0, 255), 3)
    else:
        print("方法1(霍夫圆): 未检测到圆")

    return result

def detect_circles_method2(image):
    """方法2: 颜色分割 + 轮廓检测"""
    # 转换到HSV空间
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # 检测白色圆点 (根据您的图片，圆点是白色的)
    lower_white = np.array([0, 0, 180])
    upper_white = np.array([180, 30, 255])

    mask = cv2.inRange(hsv, lower_white, upper_white)

    # 形态学操作
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    cv2.imshow('Color Mask', mask)

    # 查找轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    result = image.copy()
    circles = []

    print(f"\n方法2(颜色分割): 找到 {len(contours)} 个轮廓")

    for i, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if area < 500:  # 最小面积
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter == 0:
            continue

        circularity = 4 * np.pi * area / (perimeter ** 2)

        (x, y), radius = cv2.minEnclosingCircle(contour)

        print(f"  轮廓{i}: 面积={area:.0f}, 圆度={circularity:.3f}, 半径={radius:.1f}")

        if circularity > 0.6 and radius > 10:
            circles.append((int(x), int(y), int(radius)))
            cv2.circle(result, (int(x), int(y)), int(radius), (0, 255, 0), 2)
            cv2.circle(result, (int(x), int(y)), 2, (0, 0, 255), 3)
            cv2.putText(result, str(i), (int(x)+10, int(y)),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

    print(f"方法2(颜色分割): 检测到 {len(circles)} 个有效圆")
    return result

def detect_circles_method3(image):
    """方法3: 简单阈值 + 轮廓"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # 使用Otsu自动阈值
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    cv2.imshow('Otsu Binary', binary)

    # 查找轮廓
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    result = image.copy()
    circles = []

    print(f"\n方法3(Otsu阈值): 找到 {len(contours)} 个轮廓")

    for i, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if area < 500 or area > 50000:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter == 0:
            continue

        circularity = 4 * np.pi * area / (perimeter ** 2)

        (x, y), radius = cv2.minEnclosingCircle(contour)

        if circularity > 0.6 and 10 < radius < 100:
            circles.append((int(x), int(y), int(radius)))
            cv2.circle(result, (int(x), int(y)), int(radius), (0, 255, 0), 2)
            cv2.circle(result, (int(x), int(y)), 2, (0, 0, 255), 3)
            print(f"  找到圆: 中心=({x:.0f},{y:.0f}), 半径={radius:.1f}, 圆度={circularity:.3f}")

    print(f"方法3(Otsu阈值): 检测到 {len(circles)} 个有效圆")
    return result

def main():
    if len(sys.argv) < 2:
        print("用法: python test_detection.py <image_path>")
        return

    image_path = sys.argv[1]
    image = cv2.imread(image_path)

    if image is None:
        print(f"无法读取图像: {image_path}")
        return

    print(f"图像尺寸: {image.shape[1]}x{image.shape[0]}\n")

    # 显示原图
    cv2.imshow('Original', cv2.resize(image, (960, 540)))

    # 尝试三种方法
    result1 = detect_circles_method1(image)
    cv2.imshow('Method 1: Hough Circles', cv2.resize(result1, (960, 540)))

    result2 = detect_circles_method2(image)
    cv2.imshow('Method 2: Color Segmentation', cv2.resize(result2, (960, 540)))

    result3 = detect_circles_method3(image)
    cv2.imshow('Method 3: Otsu Threshold', cv2.resize(result3, (960, 540)))

    print("\n按任意键关闭...")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
