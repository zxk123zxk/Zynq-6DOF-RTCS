"""USB 摄像头采集与资源管理；不依赖 YOLO。

不指定 width/height 时自动按 AUTO_MODES 顺序探测宽屏模式，直到实际帧尺寸匹配。
AUTO_MODES 优先 1280×720 MJPG（全画幅高帧率），依次回落到其他模式。
"""
from __future__ import annotations

import json
import math

import cv2


BACKENDS = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "any": cv2.CAP_ANY}

# 自动宽屏探测顺序；元素为 (width, height, fourcc_or_None)
AUTO_MODES = (
    (1280, 720, None),
    (1280, 720, "MJPG"),
    (1920, 1080, "MJPG"),
    (1920, 1080, None),
    (640, 480, None),
)


class Camera:
    """摄像头封装；支持 with 语句。

    不传 width/height 时启用自动宽屏探测（推荐）。
    传入 width/height 时固定到指定分辨率（与旧调用兼容）。
    open() 之后通过 .actual 获取实际分辨率和格式信息。
    """

    def __init__(self, index: int = 1, *, backend: str = "dshow",
                 width: int | None = None, height: int | None = None) -> None:
        if index < 0 or backend not in BACKENDS:
            raise ValueError("摄像头参数无效")
        if (width is None) != (height is None):
            raise ValueError("width 和 height 必须同时提供或同时省略")
        if width is not None and (width <= 0 or height <= 0):
            raise ValueError("width/height 必须为正整数")
        self.index, self.backend = index, backend
        self.modes = ((width, height, None),) if width is not None else AUTO_MODES
        self.actual: dict = {}
        self.capture: cv2.VideoCapture | None = None

    def open(self) -> Camera:
        self._close_capture()
        for width, height, fourcc in self.modes:
            self._close_capture()
            cap = cv2.VideoCapture(self.index, BACKENDS[self.backend])
            if not cap.isOpened():
                cap.release()
                raise RuntimeError(
                    f"无法打开摄像头 {self.index}（{self.backend}）；"
                    "请关闭 Windows 相机或其他占用程序，检查权限和编号"
                )
            if fourcc:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            frame = None
            for _ in range(12):  # 丢弃前 12 帧，等自动曝光/格式协商稳定
                ok, candidate = cap.read()
                if ok and candidate is not None and candidate.size > 0:
                    frame = candidate
                else:
                    break
            if frame is None:
                cap.release()
                continue
            actual_w, actual_h = frame.shape[1], frame.shape[0]
            raw_fourcc = cap.get(cv2.CAP_PROP_FOURCC)
            code = int(raw_fourcc) if math.isfinite(raw_fourcc) else 0
            actual_fmt = "".join(chr((code >> (8 * i)) & 255) for i in range(4)).strip("\x00")
            fps = cap.get(cv2.CAP_PROP_FPS)
            self.actual = {
                "width": actual_w, "height": actual_h,
                "fourcc": actual_fmt, "backend": self.backend,
                "fps": fps if math.isfinite(fps) else None,
            }
            accepted = (actual_w == width and actual_h == height
                        and (not fourcc or fourcc == actual_fmt))
            print("CAMERA_MODE " + json.dumps(
                {"requested": [width, height, fourcc], "actual": dict(self.actual),
                 "accepted": accepted}, ensure_ascii=True), flush=True)
            if accepted:
                self.capture = cap
                return self
            cap.release()
        raise RuntimeError(
            f"摄像头 {self.index}（{self.backend}）所有模式均未匹配实际帧尺寸；"
            "请尝试 --backend msmf 或更换编号"
        )

    def _close_capture(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def read(self):
        if self.capture is None:
            raise RuntimeError("摄像头尚未打开")
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise RuntimeError("摄像头读取失败；请检查连接、占用和 OpenCV 后端")
        return frame

    def close(self) -> None:
        self._close_capture()

    def __enter__(self) -> Camera:
        return self.open()

    def __exit__(self, *_exc) -> None:
        self.close()
