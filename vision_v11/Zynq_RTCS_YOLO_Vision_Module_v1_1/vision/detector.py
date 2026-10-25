"""与摄像头和窗口解耦的 YOLO11n 单帧检测。"""
from __future__ import annotations

from pathlib import Path

import torch
from ultralytics import YOLO

from .results import Detection, FrameResult


DEFAULT_MODEL = Path(__file__).resolve().parents[1] / "models" / "best.pt"


class Detector:
    """加载交付权重；detect 接收 BGR 原始图像，输出像素框。"""

    def __init__(self, model_path: Path = DEFAULT_MODEL, *, device: str = "auto",
                 imgsz: int = 640, conf: float = 0.25) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"找不到模型：{model_path}")
        if imgsz <= 0 or not 0 <= conf <= 1:
            raise ValueError("imgsz 或 conf 无效")
        self.device = "0" if device == "auto" and torch.cuda.is_available() else device
        if self.device == "auto":
            self.device = "cpu"
        if self.device == "0" and not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用，请使用 --device cpu")
        if self.device not in {"0", "cpu"}:
            raise ValueError("device 只支持 auto、0、cpu")
        self.model = YOLO(str(model_path))
        names = {int(k): str(v).lower() for k, v in self.model.names.items()}
        if names != {0: "cube", 1: "cylinder"}:
            raise ValueError(f"模型类别不符：{self.model.names}")
        self.imgsz = imgsz
        self.conf = conf

    def detect(self, frame_bgr) -> FrameResult:
        """不裁 ROI；空检测返回空元组，绝不沿用上一帧坐标。"""
        if frame_bgr is None or getattr(frame_bgr, "ndim", None) != 3 or frame_bgr.shape[2] != 3:
            raise ValueError("需要有效的 BGR 彩色帧")
        height, width = frame_bgr.shape[:2]
        if not width or not height:
            raise ValueError("帧为空")
        result = self.model.predict(frame_bgr, imgsz=self.imgsz, conf=self.conf,
                                    device=self.device, verbose=False)[0]
        detections = []
        for box in result.boxes:
            bounds = tuple(float(v) for v in box.xyxy[0].tolist())
            detections.append(Detection.from_bbox(int(box.cls.item()), float(box.conf.item()),
                                                   bounds, width, height))
        return FrameResult(width, height, tuple(detections))
