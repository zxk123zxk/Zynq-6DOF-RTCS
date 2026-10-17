"""USB 摄像头采集与资源管理；不依赖 YOLO。"""
from __future__ import annotations

import cv2


BACKENDS = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "any": cv2.CAP_ANY}


class Camera:
    """打开摄像头并可选地设置手动曝光等控制；回读值存入 ``controls`` 供诊断。"""

    def __init__(self, index: int = 1, *, backend: str = "dshow",
                 width: int = 640, height: int = 480,
                 auto_exposure: float | None = None,
                 exposure: float | None = None,
                 gain: float | None = None) -> None:
        if index < 0 or backend not in BACKENDS or width <= 0 or height <= 0:
            raise ValueError("摄像头参数无效")
        self.index, self.backend = index, backend
        self.width, self.height = width, height
        self.auto_exposure = auto_exposure
        self.exposure = exposure
        self.gain = gain
        self.controls: dict[str, float] = {}
        self.capture = None

    def open(self) -> Camera:
        self.capture = cv2.VideoCapture(self.index, BACKENDS[self.backend])
        if not self.capture.isOpened():
            self.close()
            raise RuntimeError(f"无法打开摄像头 {self.index}（{self.backend}）；请检查编号、占用和系统权限")
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        # 相机控制：打开后立即设置并回读；写失败保留回读值，不视为致命错误。
        for name, prop, value in (
                ("auto_exposure", cv2.CAP_PROP_AUTO_EXPOSURE, self.auto_exposure),
                ("exposure", cv2.CAP_PROP_EXPOSURE, self.exposure),
                ("gain", cv2.CAP_PROP_GAIN, self.gain)):
            if value is None:
                continue
            self.capture.set(prop, value)
            self.controls[name] = self.capture.get(prop)
        return self

    def read(self):
        if self.capture is None:
            raise RuntimeError("摄像头尚未打开")
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise RuntimeError("摄像头读取失败；请检查连接、占用和 OpenCV 后端")
        return frame

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def __enter__(self) -> Camera:
        return self.open()

    def __exit__(self, *_exc) -> None:
        self.close()
