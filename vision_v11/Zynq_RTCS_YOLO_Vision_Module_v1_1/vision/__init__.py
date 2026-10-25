"""可复用的 Cube/Cylinder 像素检测接口。"""
from .detector import Detector
from .results import Detection, FrameResult

__all__ = ["Detector", "Detection", "FrameResult"]
