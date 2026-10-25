"""
简单的圆形检测测试 - 不弹窗，直接保存结果
"""

import cv2
import numpy as np
import sys

def test_detection(image_path):
    """测试圆形检测并保存结果"""

    # 读取图像
    image = cv2.imread(image_path)
    if image is None:
        print(f"无法读取图像: {image_path}")
        return

    print(f"图像尺寸: {image.shape[1]}x{image.shape[0]}")

    # === 方法1: 霍夫圆检测 ===
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray_blur = cv2.GaussianBlur(gray, (9, 9), 2)

    circles = cv2.HoughCircles(
        gray_blur,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=50,
        param1=50,
        param2=30,
        minRadius=15,
        maxRadius=80
    )

    result1 = image.copy()
    if circles is not None:
        circles = np.uint16(np.around(circles))
        print(f"\n霍夫圆检测: 找到 {len(circles[0])} 个圆")
        for i, (x, y, r) in enumerate(circles[0, :]):
            print(f"  圆{i}: 中心=({x}, {y}), 半径={r}")
            cv2.circle(result1, (x, y), r, (0, 255, 0), 3)
            cv2.circle(result1, (x, y), 2, (0, 0, 255), -1)
            cv2.putText(result1, f"{i}", (x+10, y-10),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
    else:
        print("\n霍夫圆检测: 未找到圆")

    cv2.imwrite('result_hough.jpg', result1)
    print("已保存: result_hough.jpg")

    # === 方法2: 颜色分割 ===
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # 白色范围
    lower_white = np.array([0, 0, 200])
    upper_white = np.array([180, 30, 255])
    mask = cv2.inRange(hsv, lower_white, upper_white)

    # 形态学处理
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    cv2.imwrite('result_mask.jpg', mask)
    print("已保存: result_mask.jpg")

    # 查找轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    result2 = image.copy()
    valid_circles = []

    print(f"\n颜色分割: 找到 {len(contours)} 个轮廓")

    for i, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if area < 300:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter == 0:
            continue

        circularity = 4 * np.pi * area / (perimeter ** 2)
        (x, y), radius = cv2.minEnclosingCircle(contour)

        print(f"  轮廓{i}: 面积={area:.0f}, 圆度={circularity:.3f}, 半径={radius:.1f}")

        if circularity > 0.6 and 15 < radius < 80:
            valid_circles.append((int(x), int(y), int(radius)))
            cv2.circle(result2, (int(x), int(y)), int(radius), (0, 255, 0), 3)
            cv2.circle(result2, (int(x), int(y)), 2, (0, 0, 255), -1)
            cv2.putText(result2, f"{len(valid_circles)-1}", (int(x)+10, int(y)-10),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

    print(f"颜色分割: 找到 {len(valid_circles)} 个有效圆")

    cv2.imwrite('result_color.jpg', result2)
    print("已保存: result_color.jpg")

    # === 如果找到4个圆，进行排序 ===
    if len(valid_circles) == 4:
        print("\n找到4个圆，进行角点排序:")
        points = np.array([(x, y) for x, y, r in valid_circles])

        # 计算质心
        centroid = np.mean(points, axis=0)

        # 按角度排序
        angles = np.arctan2(points[:, 1] - centroid[1],
                           points[:, 0] - centroid[0])
        angles = (angles + np.pi * 5/4) % (2 * np.pi)
        sorted_indices = np.argsort(angles)

        sorted_points = points[sorted_indices]

        corner_names = ['左上', '右上', '右下', '左下']
        result3 = image.copy()
        colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 0)]

        for i, (point, name, color) in enumerate(zip(sorted_points, corner_names, colors)):
            x, y = int(point[0]), int(point[1])
            print(f"  {name}: ({x}, {y})")
            cv2.circle(result3, (x, y), 30, color, 3)
            cv2.putText(result3, name, (x+15, y-15),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        # 绘制边界
        corners_int = sorted_points.astype(np.int32)
        cv2.polylines(result3, [corners_int], True, (0, 255, 255), 3)

        # 绘制中心
        center = tuple(centroid.astype(int))
        cv2.circle(result3, center, 5, (255, 0, 255), -1)
        cv2.putText(result3, 'Center', (center[0]+10, center[1]),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 2)

        cv2.imwrite('result_sorted.jpg', result3)
        print("已保存: result_sorted.jpg")

    print("\n测试完成!")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python simple_test.py <image_path>")
    else:
        test_detection(sys.argv[1])
