"""工作平面四点标定：原图像素与传送带毫米坐标互转。

四个角点按点击顺序对应：
  第 1 点 = 原点 (0, 0)
  第 2 点 = +x 轴上距离 length_mm 的点
  第 3 点 = 对角点 (length_mm, width_mm)
  第 4 点 = +y 轴上距离 width_mm 的点

对绿色传送带，即以左下角为原点、沿传送带长度方向为 +x、沿宽度方向为 +y。
只对标定所在平面有效；未做镜头畸变校正，物体高出平面时存在视差。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import json
from math import isfinite
from pathlib import Path

import cv2
import numpy as np


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "calibration.json"
CORNER_ROLE = ("origin", "+x", "opposite", "+y")


@dataclass(frozen=True)
class PlaneCalibration:
    corners_px: tuple[tuple[float, float], ...]  # 原点、+x、对角、+y，原图像素
    board_mm: tuple[float, float]  # 沿 x 轴长度、沿 y 轴宽度
    image_size: tuple[int, int]  # 标定时的帧宽、帧高

    def __post_init__(self) -> None:
        if len(self.corners_px) != 4 or not all(len(p) == 2 and all(map(isfinite, p))
                                                for p in self.corners_px):
            raise ValueError("需要 4 个有限的角点")
        if min(self.board_mm) <= 0 or min(self.image_size) <= 0:
            raise ValueError("标定板尺寸和图像尺寸必须为正数")
        quad = np.array(self.corners_px, dtype=np.float32)
        if abs(cv2.contourArea(quad)) < 100:
            raise ValueError("四个角点几乎共线或重合")
        if not cv2.isContourConvex(quad):
            raise ValueError("角点顺序错误：应沿传送带边缘依次点击 原点 → +x → 对角 → +y")

    @classmethod
    def from_corners(cls, corners, board_mm, image_size) -> PlaneCalibration:
        return cls(tuple((float(x), float(y)) for x, y in corners),
                   (float(board_mm[0]), float(board_mm[1])),
                   (int(image_size[0]), int(image_size[1])))

    @cached_property
    def homography(self) -> np.ndarray:
        """像素 → 毫米的 3x3 透视矩阵。"""
        length, width = self.board_mm
        dst = np.array([[0, 0], [length, 0], [length, width], [0, width]], dtype=np.float32)
        src = np.array(self.corners_px, dtype=np.float32)  # getPerspectiveTransform 只接受 float32
        return cv2.getPerspectiveTransform(src, dst).astype(np.float64)

    @cached_property
    def inverse(self) -> np.ndarray:
        return np.linalg.inv(self.homography)

    def to_mm(self, x: float, y: float) -> tuple[float, float]:
        return _apply(self.homography, x, y)

    def to_px(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        return _apply(self.inverse, x_mm, y_mm)

    def for_size(self, width: int, height: int) -> PlaneCalibration:
        """按比例换算到其他分辨率；仅当摄像头只缩放、不裁剪视野时成立。"""
        sx, sy = width / self.image_size[0], height / self.image_size[1]
        return PlaneCalibration(tuple((x * sx, y * sy) for x, y in self.corners_px),
                                self.board_mm, (width, height))

    def save(self, path: Path = DEFAULT_PATH) -> None:
        data = {"corner_order": list(CORNER_ROLE),
                "corners_px": [list(p) for p in self.corners_px],
                "board_mm": list(self.board_mm),
                "image_size": list(self.image_size),
                "homography_px_to_mm": self.homography.tolist()}
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> PlaneCalibration:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_corners(data["corners_px"], data["board_mm"], data["image_size"])


def _apply(matrix: np.ndarray, x: float, y: float) -> tuple[float, float]:
    out = cv2.perspectiveTransform(np.array([[[x, y]]], dtype=np.float64), matrix)[0, 0]
    return float(out[0]), float(out[1])
