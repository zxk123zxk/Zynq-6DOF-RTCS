"""动态检测传送带边界，手动确认后保存为固定标定。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision.belt_detector import BeltDetector
from vision.camera import Camera
from vision.plane_calibration import PlaneCalibration, DEFAULT_PATH


WINDOW = "Belt Auto-Detection | SPACE confirm | R retry | Q quit"


def draw_detection_result(frame, belt: BeltDetector, frozen: bool = False):
    """绘制检测结果和操作提示。"""
    image = frame.copy()

    if belt.is_ready():
        # 绘制传送带边界
        corners = [tuple(map(int, pt)) for pt in belt.corners_px]
        for i in range(4):
            cv2.line(image, corners[i], corners[(i + 1) % 4], (0, 255, 255), 3)

        labels = ["BL(0,0)", "BR", "TR", "TL"]
        for corner, label in zip(corners, labels):
            cv2.circle(image, corner, 8, (0, 255, 255), -1)
            cv2.putText(image, label, (corner[0] + 12, corner[1] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        # 显示提示信息
        status = "FROZEN - Press SPACE to save" if frozen else "Press SPACE to freeze and confirm"
        cv2.rectangle(image, (0, 0), (image.shape[1], 80), (0, 100, 0) if frozen else (0, 0, 0), -1)
        cv2.putText(image, "Belt detected!", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(image, status, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    else:
        # 未检测到传送带
        cv2.rectangle(image, (0, 0), (image.shape[1], 80), (0, 0, 100), -1)
        cv2.putText(image, "Detecting belt... Adjust camera angle if needed",
                    (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    return image


def main() -> int:
    parser = argparse.ArgumentParser(
        description="动态检测传送带边界，确认后保存为固定标定"
    )
    parser.add_argument("--camera-index", type=int, default=1)
    parser.add_argument("--backend", choices=("dshow", "msmf", "any"), default="msmf")
    parser.add_argument("--width", type=int, default=1280,
                        help="相机分辨率宽度，标定后必须与 camera_demo.py 一致")
    parser.add_argument("--height", type=int, default=720,
                        help="相机分辨率高度，标定后必须与 camera_demo.py 一致")
    parser.add_argument("--belt-width", type=float, default=490.0,
                        help="传送带实际宽度（毫米），默认 490")
    parser.add_argument("--belt-height", type=float, default=80.0,
                        help="传送带实际高度（毫米），默认 80")
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH,
                        help="标定文件保存路径")
    args = parser.parse_args()

    print(f"传送带尺寸：{args.belt_width} x {args.belt_height} mm")
    print(f"标定文件将保存到：{args.output}")
    print("\n操作说明：")
    print("  - 自动检测会实时显示黄色边界框")
    print("  - 调整相机角度，确保边界框准确贴合传送带")
    print("  - 按 SPACE 键冻结当前检测结果")
    print("  - 确认无误后，再按 SPACE 保存标定")
    print("  - 按 R 键重新检测")
    print("  - 按 Q 键退出\n")

    try:
        with Camera(args.camera_index, backend=args.backend,
                    width=args.width, height=args.height) as camera:
            actual_width = camera.actual["width"]
            actual_height = camera.actual["height"]
            print(f"摄像头分辨率：{actual_width}x{actual_height} "
                  f"{camera.actual.get('fourcc', 'unknown')}\n")

            belt = BeltDetector(belt_width_mm=args.belt_width,
                               belt_height_mm=args.belt_height)

            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

            frozen = False
            frozen_frame = None
            frozen_belt_corners = None

            while True:
                if not frozen:
                    frame = camera.read()
                    belt.detect(frame)
                else:
                    frame = frozen_frame

                cv2.imshow(WINDOW, draw_detection_result(frame, belt, frozen))

                key = cv2.waitKey(1) & 0xFF

                if key in (ord('q'), ord('Q'), 27):
                    print("用户取消")
                    break

                elif key == ord(' '):
                    if not frozen:
                        if belt.is_ready():
                            frozen = True
                            frozen_frame = frame.copy()
                            frozen_belt_corners = belt.corners_px.copy()
                            print("\n检测结果已冻结，请确认边界是否准确")
                            print("  - 满意：再按一次 SPACE 保存")
                            print("  - 不满意：按 R 重新检测")
                        else:
                            print("未检测到传送带，无法冻结")
                    else:
                        frame_size = (frozen_frame.shape[1], frozen_frame.shape[0])
                        calib = PlaneCalibration.from_corners(
                            frozen_belt_corners,
                            (args.belt_width, args.belt_height),
                            frame_size
                        )
                        calib.save(args.output)
                        print(f"\n✓ 标定已保存：{args.output}")
                        print(f"  分辨率：{frame_size[0]}x{frame_size[1]}")
                        print(f"  传送带尺寸：{args.belt_width} x {args.belt_height} mm")
                        print("\n后续使用 camera_demo.py 时会自动加载此标定")
                        break

                elif key in (ord('r'), ord('R')):
                    frozen = False
                    frozen_frame = None
                    frozen_belt_corners = None
                    print("\n重新检测中...")

                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break

    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
