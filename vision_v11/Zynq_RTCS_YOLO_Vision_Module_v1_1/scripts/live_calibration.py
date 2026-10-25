"""实时工作平面标定与效果检查（绿色传送带坐标系）。

流程：画面中依次左键点击传送带的 左下角 → 右下角 → 右上角 → 左上角，
程序自动叠加毫米网格；之后左键点任意位置显示其毫米坐标，
相邻两点显示距离，用尺子上的已知刻度核对误差。

坐标：左下角为原点，沿传送带长度方向为 +x，沿宽度方向为 +y。

CMD 命令（在本窗口输入后回车，无需切回图像窗口）：
  save/s 保存   reset/r 重来   undo/u 撤销   print/p 查看结果
  grid/g 网格   help 帮助      quit/q 退出
图像窗口按键：S 保存  R 重置  右键撤销  空格冻结  G 网格  Q 退出
"""
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import argparse
from math import hypot
from pathlib import Path
import sys

import cv2
import numpy as np

try:
    import msvcrt  # Windows 控制台非阻塞读键
except ImportError:  # 非 Windows 平台退化为只能用窗口按键
    msvcrt = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision.camera import Camera
from vision.plane_calibration import DEFAULT_PATH, PlaneCalibration


WINDOW = "Belt Calibration - type 'save' in CMD | R reset | Q quit"
CORNER_NAMES = ("BL origin", "BR +x", "TR corner", "TL +y")
CORNER_COLORS = ((0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255))
COMMAND_HELP = ("命令：save 保存 | reset 重来 | undo 撤销 | print 查看 | "
                "grid 网格 | help 帮助 | quit 退出（输入后按回车）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="绿色传送带实时标定与效果检查")
    parser.add_argument("--belt-length", type=float, default=490.0,
                        help="传送带长度 (mm)，左下→右下 (默认 490)")
    parser.add_argument("--belt-width", type=float, default=80.0,
                        help="传送带宽度 (mm)，左下→左上 (默认 80)")
    parser.add_argument("--camera-index", type=int, default=1)
    parser.add_argument("--backend", choices=("dshow", "msmf", "any"), default="msmf")
    parser.add_argument("--width", type=int, help="固定分辨率宽度；不传时自动探测宽屏模式（推荐）")
    parser.add_argument("--height", type=int, help="固定分辨率高度；不传时自动探测")
    parser.add_argument("--grid", type=float, default=10.0, help="网格间距 (mm)")
    parser.add_argument("--max-display-width", type=int, default=1280)
    parser.add_argument("--max-display-height", type=int, default=720)
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--load", action="store_true", help="载入已保存的角点继续检查")
    parser.add_argument("--no-stdin", action="store_true", help="不读取 CMD 命令，只用窗口按键")
    return parser


class ConsoleInput:
    """Windows 控制台非阻塞行输入，不影响 OpenCV 窗口显示。"""

    def __init__(self) -> None:
        self.buffer = ""

    def poll(self) -> list[str]:
        """返回这一轮已按回车提交的命令（小写）。"""
        if msvcrt is None:
            return []
        lines = []
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                print(flush=True)
                lines.append(self.buffer.strip().lower())
                self.buffer = ""
            elif ch == "\x08":  # 退格
                if self.buffer:
                    self.buffer = self.buffer[:-1]
                    print("\b \b", end="", flush=True)
            elif ch == "\x1b":  # Esc 清空当前输入
                self.buffer = ""
                print(flush=True)
            elif ch.isprintable():
                self.buffer += ch
                print(ch, end="", flush=True)
            # 方向键等以 \x00/\xe0 开头的两字节序列直接忽略
        return [line for line in lines if line]


class Session:
    def __init__(self, args, frame_size: tuple[int, int]) -> None:
        self.args, self.frame_size = args, frame_size
        w, h = frame_size
        self.scale = min(1.0, args.max_display_width / w, args.max_display_height / h)
        self.corners: list[tuple[float, float]] = []
        self.probes: list[tuple[float, float]] = []
        self.calib: PlaneCalibration | None = None
        self.cursor: tuple[float, float] | None = None
        self.show_grid = True

    def set_corners(self, corners) -> None:
        self.corners, self.probes, self.calib = list(corners), [], None
        if len(self.corners) == 4:
            try:
                self.calib = PlaneCalibration.from_corners(
                    self.corners, (self.args.belt_length, self.args.belt_width), self.frame_size)
                print("标定完成：在 CMD 输入 save 回车保存，或先点击画面核对毫米坐标", flush=True)
            except ValueError as exc:
                print(f"角点无效：{exc}；已撤销最后一点", flush=True)
                self.corners.pop()

    def undo(self) -> None:
        """先撤销测量点，再撤销角点。"""
        if self.probes:
            self.probes.pop()
            print(f"已撤销测量点，剩 {len(self.probes)} 个", flush=True)
        elif self.corners:
            self.set_corners(self.corners[:-1])
            print(f"已撤销角点，剩 {len(self.corners)}/4", flush=True)
        else:
            print("没有可撤销的内容", flush=True)

    def on_mouse(self, event, x, y, _flags, _param) -> None:
        point = (x / self.scale, y / self.scale)  # 显示坐标 → 原图像素
        self.cursor = point
        if event == cv2.EVENT_LBUTTONDOWN:
            if self.calib is None:
                print(f"{CORNER_NAMES[len(self.corners)]}: "
                      f"({point[0]:.1f}, {point[1]:.1f}) px", flush=True)
                self.set_corners(self.corners + [point])
            else:
                self.probes = (self.probes + [point])[-2:]
                mm = self.calib.to_mm(*point)
                print(f"点 ({point[0]:.1f}, {point[1]:.1f}) px → ({mm[0]:.1f}, {mm[1]:.1f}) mm", flush=True)
                if len(self.probes) == 2:
                    print(f"  两点距离 {self._distance_mm():.1f} mm", flush=True)
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.undo()

    def _distance_mm(self) -> float:
        (ax, ay), (bx, by) = (self.calib.to_mm(*p) for p in self.probes)
        return hypot(ax - bx, ay - by)

    def render(self, frame) -> np.ndarray:
        image = frame.copy()
        if self.calib is not None and self.show_grid:
            self._draw_grid(image)
        for i, p in enumerate(self.corners):
            pt = _ipt(p)
            cv2.circle(image, pt, 5, CORNER_COLORS[i], -1)
            cv2.putText(image, CORNER_NAMES[i], (pt[0] + 8, pt[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, CORNER_COLORS[i], 2)
        if len(self.corners) >= 2:
            cv2.polylines(image, [np.array(self.corners, np.int32)], self.calib is not None,
                          (0, 255, 255), 1)
        for p in self.probes:
            cv2.drawMarker(image, _ipt(p), (255, 0, 255), cv2.MARKER_CROSS, 16, 2)
            mm = self.calib.to_mm(*p)
            cv2.putText(image, f"({mm[0]:.1f},{mm[1]:.1f})mm", (_ipt(p)[0] + 8, _ipt(p)[1] + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
        if len(self.probes) == 2:
            cv2.line(image, _ipt(self.probes[0]), _ipt(self.probes[1]), (255, 0, 255), 1)

        display = cv2.resize(image, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA) \
            if self.scale < 1 else image
        self._draw_status(display)
        self._draw_magnifier(frame, display)
        return display

    def _draw_grid(self, image) -> None:
        length, width = self.calib.board_mm
        step = self.args.grid
        for x in np.arange(0, length + 1e-6, step):
            cv2.line(image, _ipt(self.calib.to_px(x, 0)), _ipt(self.calib.to_px(x, width)),
                     (0, 200, 0), 1)
        for y in np.arange(0, width + 1e-6, step):
            cv2.line(image, _ipt(self.calib.to_px(0, y)), _ipt(self.calib.to_px(length, y)),
                     (0, 200, 0), 1)
        origin = _ipt(self.calib.to_px(0, 0))
        for end, label in ((self.calib.to_px(min(length, 5 * step), 0), "X"),
                           (self.calib.to_px(0, min(width, 5 * step)), "Y")):
            cv2.arrowedLine(image, origin, _ipt(end), (0, 0, 255), 2, tipLength=0.15)
            cv2.putText(image, label, _ipt(end), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    def _draw_status(self, display) -> None:
        if self.calib is None:
            text = f"Click belt corner {len(self.corners) + 1}/4: {CORNER_NAMES[len(self.corners)]}"
        else:
            text = (f"Belt {self.calib.board_mm[0]:g}x{self.calib.board_mm[1]:g} mm"
                    f" | origin = belt bottom-left | type 'save' in CMD")
            if self.cursor is not None:
                mm = self.calib.to_mm(*self.cursor)
                text += f" | cursor ({mm[0]:.1f},{mm[1]:.1f}) mm"
            if len(self.probes) == 2:
                text += f" | dist {self._distance_mm():.1f} mm"
        cv2.rectangle(display, (0, 0), (display.shape[1], 28), (0, 0, 0), -1)
        cv2.putText(display, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    def _draw_magnifier(self, frame, display, radius: int = 20, size: int = 160) -> None:
        """光标附近原图放大，便于精确点角点。"""
        if self.cursor is None:
            return
        cx, cy = _ipt(self.cursor)
        h, w = frame.shape[:2]
        x0, y0 = min(max(cx - radius, 0), w - 2 * radius), min(max(cy - radius, 0), h - 2 * radius)
        patch = cv2.resize(frame[y0:y0 + 2 * radius, x0:x0 + 2 * radius], (size, size),
                           interpolation=cv2.INTER_NEAREST)
        k = size / (2 * radius)
        px, py = int((cx - x0 + 0.5) * k), int((cy - y0 + 0.5) * k)
        cv2.line(patch, (px, 0), (px, size), (0, 0, 255), 1)
        cv2.line(patch, (0, py), (size, py), (0, 0, 255), 1)
        dh, dw = display.shape[:2]
        if size + 40 > dh or size + 10 > dw:
            return
        display[dh - size - 10:dh - 10, dw - size - 10:dw - 10] = patch
        cv2.rectangle(display, (dw - size - 11, dh - size - 11), (dw - 9, dh - 9), (255, 255, 255), 1)


def show_calibration(session: Session, args) -> None:
    """在 CMD 打印当前标定，并验证四个角点的换算结果。"""
    if session.calib is None:
        print(f"尚未完成标定（已点 {len(session.corners)}/4 个角点）", flush=True)
        return
    calib = session.calib
    length, width = calib.board_mm
    print(f"传送带坐标系：原点=左下角，+x 沿长度，+y 沿宽度；"
          f"长度 {length:g} mm，宽度 {width:g} mm", flush=True)
    print(f"标定分辨率：{calib.image_size[0]}x{calib.image_size[1]}", flush=True)
    expected = ((0, 0), (length, 0), (length, width), (0, width))
    for role, px, (ex, ey) in zip(CORNER_NAMES, calib.corners_px, expected):
        x, y = calib.to_mm(*px)
        print(f"  {role:<11} px({px[0]:7.1f},{px[1]:7.1f}) → "
              f"({x:7.1f},{y:7.1f}) mm  应为 ({ex:g},{ey:g})", flush=True)
    print(f"文件：{args.output}", flush=True)


def save_calibration(session: Session, args) -> None:
    if session.calib is None:
        print(f"还不能保存：已点 {len(session.corners)}/4 个角点", flush=True)
        return
    session.calib.save(args.output)
    print(f"已保存：{args.output}", flush=True)
    show_calibration(session, args)


def handle_command(command: str, session: Session, args) -> bool:
    """执行一条 CMD 命令；返回 False 表示退出。"""
    if command in ("q", "quit", "exit"):
        return False
    if command in ("s", "save", "w", "write"):
        save_calibration(session, args)
    elif command in ("r", "reset", "clear"):
        session.set_corners([])
        print("已清除角点，请重新点击 左下→右下→右上→左上", flush=True)
    elif command in ("u", "undo"):
        session.undo()
    elif command in ("p", "print", "show", "info"):
        show_calibration(session, args)
    elif command in ("g", "grid"):
        session.show_grid = not session.show_grid
        print(f"网格：{'开' if session.show_grid else '关'}", flush=True)
    elif command in ("h", "help", "?"):
        print(COMMAND_HELP, flush=True)
    else:
        print(f"未知命令：{command}", flush=True)
    return True


def _ipt(p) -> tuple[int, int]:
    return round(p[0]), round(p[1])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.belt_length <= 0 or args.belt_width <= 0 or args.grid <= 0:
        raise SystemExit("传送带尺寸和网格间距必须为正数")
    try:
        with Camera(args.camera_index, backend=args.backend,
                    width=args.width, height=args.height) as camera:
            frame = camera.read()
            size = (frame.shape[1], frame.shape[0])
            print(f"摄像头实际分辨率：{size[0]}x{size[1]}", flush=True)
            session = Session(args, size)
            if args.load:
                saved = PlaneCalibration.load(args.output)
                if saved.image_size != size:
                    raise SystemExit(f"已保存标定的分辨率 {saved.image_size} 与当前 {size} 不同，请重新标定")
                args.belt_length, args.belt_width = saved.board_mm
                session.set_corners(saved.corners_px)
            cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)  # 不允许拉伸窗口，保证鼠标坐标换算准确
            cv2.setMouseCallback(WINDOW, session.on_mouse)
            console = None if args.no_stdin else ConsoleInput()
            frozen = False
            print(__doc__, flush=True)
            print(COMMAND_HELP, flush=True)
            running = True
            while running:
                if console is not None:
                    for command in console.poll():
                        if not handle_command(command, session, args):
                            running = False
                            break
                if not running:
                    break
                if not frozen:
                    frame = camera.read()
                cv2.imshow(WINDOW, session.render(frame))
                key = cv2.waitKey(15) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    break
                if key == ord(" "):
                    frozen = not frozen
                elif key in (ord("r"), ord("R")):
                    session.set_corners([])
                elif key in (ord("g"), ord("G")):
                    session.show_grid = not session.show_grid
                elif key in (ord("s"), ord("S"), ord("w"), ord("W")):
                    save_calibration(session, args)
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
