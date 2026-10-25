"""测试标定精度：点击画面显示毫米坐标，用尺子验证。"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision.camera import Camera
from vision.plane_calibration import PlaneCalibration, DEFAULT_PATH


class ClickTest:
    def __init__(self, calibration: PlaneCalibration):
        self.calib = calibration
        self.points = []  # 存储最近点击的两个点
        self.cursor = None

    def on_mouse(self, event, x, y, flags, param):
        self.cursor = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            mm = self.calib.to_mm(x, y)
            self.points = (self.points + [(x, y)])[-2:]
            print(f"点击 ({x:4d}, {y:4d}) px → ({mm[0]:6.1f}, {mm[1]:6.1f}) mm", flush=True)
            if len(self.points) == 2:
                (x1, y1), (x2, y2) = self.points
                mm1, mm2 = self.calib.to_mm(x1, y1), self.calib.to_mm(x2, y2)
                dist = ((mm1[0] - mm2[0])**2 + (mm1[1] - mm2[1])**2)**0.5
                print(f"  两点距离：{dist:.1f} mm", flush=True)

    def render(self, frame):
        image = frame.copy()
        # 画传送带边界
        for i in range(4):
            pt1 = tuple(map(round, self.calib.corners_px[i]))
            pt2 = tuple(map(round, self.calib.corners_px[(i + 1) % 4]))
            cv2.line(image, pt1, pt2, (0, 255, 255), 2)

        # 画原点和坐标轴
        origin = tuple(map(round, self.calib.to_px(0, 0)))
        x_axis = tuple(map(round, self.calib.to_px(50, 0)))
        y_axis = tuple(map(round, self.calib.to_px(0, 50)))
        cv2.circle(image, origin, 5, (0, 0, 255), -1)
        cv2.arrowedLine(image, origin, x_axis, (0, 0, 255), 2, tipLength=0.2)
        cv2.arrowedLine(image, origin, y_axis, (0, 255, 0), 2, tipLength=0.2)
        cv2.putText(image, "X", x_axis, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(image, "Y", y_axis, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(image, "Origin", (origin[0] + 8, origin[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        # 画点击的点
        for pt in self.points:
            cv2.drawMarker(image, pt, (255, 0, 255), cv2.MARKER_CROSS, 20, 2)
            mm = self.calib.to_mm(*pt)
            cv2.putText(image, f"({mm[0]:.1f},{mm[1]:.1f})mm",
                        (pt[0] + 10, pt[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
        if len(self.points) == 2:
            cv2.line(image, self.points[0], self.points[1], (255, 0, 255), 2)

        # 光标位置的毫米坐标
        if self.cursor:
            mm = self.calib.to_mm(*self.cursor)
            text = f"Cursor: ({mm[0]:.1f}, {mm[1]:.1f}) mm"
            cv2.rectangle(image, (0, 0), (image.shape[1], 30), (0, 0, 0), -1)
            cv2.putText(image, text, (10, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return image


def main():
    try:
        calib = PlaneCalibration.load(DEFAULT_PATH)
        print(f"已加载标定：{DEFAULT_PATH}")
        print(f"传送带尺寸：{calib.board_mm[0]} x {calib.board_mm[1]} mm")
        print(f"标定分辨率：{calib.image_size[0]}x{calib.image_size[1]}")
    except Exception as e:
        print(f"无法加载标定文件：{e}")
        print("请先运行 live_calibration.py 完成标定")
        return 1

    try:
        with Camera(1, backend="msmf") as camera:
            actual_w = camera.actual["width"]
            actual_h = camera.actual["height"]
            print(f"摄像头分辨率：{actual_w}x{actual_h}")

            if (actual_w, actual_h) != calib.image_size:
                print(f"警告：分辨率不一致！标定时为 {calib.image_size}，请重新标定")
                return 1

            tester = ClickTest(calib)
            window = "Calibration Test - Click to measure | Q quit"
            cv2.namedWindow(window)
            cv2.setMouseCallback(window, tester.on_mouse)

            print("\n=== 标定精度测试 ===")
            print("左键点击画面上的位置，显示毫米坐标")
            print("点击两处会显示它们之间的距离")
            print("用尺子测量同样两点，对比距离验证精度")
            print("按 Q 退出\n")

            while True:
                frame = camera.read()
                cv2.imshow(window, tester.render(frame))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord('q'), ord('Q'), 27):
                    break
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
