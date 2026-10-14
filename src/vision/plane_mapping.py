"""Workspace plane mapping: image pixels to plane millimetres under a fixed camera."""
# SPDX-License-Identifier: AGPL-3.0-only
# 职责：把固定相机、固定工作平面上的像素中心 (u,v) 映射为工作平面毫米坐标 (x,y)，
#       并用独立验证点与凸包有效性检查拒绝未标定或超界输入。
# 本模块不做相机内参/畸变标定，也不做 Workspace -> Robot Base 外参变换。
# 方案依据：docs/4.G4-static-vision-grasp.md 与 docs/vision/milestones/V1.1_*.md。
#
# 三个阶段（一条链路，前一个的输出是后一个的输入）：
#   collect   把"放在已知工作坐标上的工件"实拍图跑现有 YOLO，导出像素中心 -> 点对 CSV
#   calibrate 用点对求映射，按独立验证点报误差，写出 config/workspace_plane.yaml
#   map       运行时把 (u,v) 转成 (x,y) 毫米；凸包外/配置不符直接拒绝，不外推

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import numpy as np

SCHEMA_VERSION = 1
METHODS = ("homography", "poly2")
SPLITS = ("calibrate", "validate")
POLY_BASIS_SIZE = 6
DEFAULT_MARGIN_PX = 0.0
DEFAULT_MAX_ERROR_MM = 2.0
# 像素尺度下限：低于此值说明 1 个像素对应超过 0.5 mm，
# 定位误差预算（目标 <2 mm）几乎没有余量，应先解决分辨率而不是继续调参。
ENOUGH_PX_PER_MM = 2.0

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = PROJECT_ROOT / "models/vision/yolo_a_cube_cylinder_best.pt"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
POINT_IMAGE_PATTERN = re.compile(r"^(-?\d+)_(-?\d+)_(\d+)$")
CSV_FIELDS = ("name", "u", "v", "x_mm", "y_mm", "split", "detections", "confidence")


# --------------------------------------------------------------------------
# 点对与误差
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationPoint:
    """一个实测点对：像素中心 ``(u, v)`` 与工作平面毫米 ``(x_mm, y_mm)``。

    ``split`` 只允许 ``calibrate``（参与求解）与 ``validate``（独立验证）。
    两类点必须严格分离：验证点绝不参与拟合，否则报出的误差不是独立误差。
    """

    name: str
    u: float
    v: float
    x_mm: float
    y_mm: float
    split: str = "calibrate"

    def __post_init__(self) -> None:
        if self.split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}")
        if not self.name:
            raise ValueError("name must not be empty")
        for field_name in ("u", "v", "x_mm", "y_mm"):
            value = getattr(self, field_name)
            if not np.isfinite(value):
                raise ValueError(f"{field_name} must be finite")

    def to_dict(self) -> dict:
        """转换为可 YAML/JSON 序列化的字典，保持像素与毫米单位不变。"""
        return {
            "name": self.name,
            "u": float(self.u),
            "v": float(self.v),
            "x_mm": float(self.x_mm),
            "y_mm": float(self.y_mm),
            "split": self.split,
        }


@dataclass(frozen=True)
class PointError:
    """单个点的映射残差；单位毫米，含它在哪一侧（校准/验证）。"""

    name: str
    split: str
    error_mm: float

    def to_dict(self) -> dict:
        return {"name": self.name, "split": self.split, "error_mm": float(self.error_mm)}


@dataclass(frozen=True)
class ValidationReport:
    """按校准点与独立验证点分别统计的定位误差。"""

    n_calibrate: int
    n_validate: int
    calibrate_mean_mm: float | None
    calibrate_rms_mm: float | None
    calibrate_max_mm: float | None
    validate_mean_mm: float | None
    validate_rms_mm: float | None
    validate_max_mm: float | None
    points: tuple[PointError, ...]

    def passed(self, max_error_mm: float) -> bool:
        """独立验证点存在且其最大残差不超过阈值才算通过。"""
        return self.n_validate > 0 and self.validate_max_mm is not None and self.validate_max_mm <= max_error_mm

    def to_dict(self) -> dict:
        return {
            "n_calibrate": int(self.n_calibrate),
            "n_validate": int(self.n_validate),
            "calibrate_mean_mm": _opt_float(self.calibrate_mean_mm),
            "calibrate_rms_mm": _opt_float(self.calibrate_rms_mm),
            "calibrate_max_mm": _opt_float(self.calibrate_max_mm),
            "validate_mean_mm": _opt_float(self.validate_mean_mm),
            "validate_rms_mm": _opt_float(self.validate_rms_mm),
            "validate_max_mm": _opt_float(self.validate_max_mm),
            "points": [point.to_dict() for point in self.points],
        }


def _opt_float(value: float | None) -> float | None:
    """把可选数值转成原生 float，避免 numpy 标量进入 YAML。"""
    return None if value is None else float(value)


def _summarize(errors: list[float]) -> tuple[float | None, float | None, float | None]:
    """返回 (mean, rms, max)；空列表返回三个 None。"""
    if not errors:
        return None, None, None
    values = np.asarray(errors, dtype=float)
    return float(values.mean()), float(np.sqrt((values ** 2).mean())), float(values.max())


# --------------------------------------------------------------------------
# 求解：像素 -> 毫米
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageNormalization:
    """像素坐标归一化参数；二次多项式必须与求解时用同一套参数。"""

    cu: float
    cv: float
    scale: float

    @classmethod
    def from_points(cls, image_uv: np.ndarray) -> "ImageNormalization":
        points = np.asarray(image_uv, dtype=float)
        cu, cv = (float(value) for value in points.mean(axis=0))
        shifted = points - (cu, cv)
        scale = float(np.sqrt((shifted ** 2).sum(axis=1)).mean())
        return cls(cu=cu, cv=cv, scale=scale if np.isfinite(scale) and scale > 0 else 1.0)

    def apply(self, image_uv: np.ndarray) -> np.ndarray:
        points = np.asarray(image_uv, dtype=float)
        return (points - (self.cu, self.cv)) / self.scale


def _poly_basis(normalized_uv: np.ndarray) -> np.ndarray:
    """二次基 ``[1, un, vn, un^2, un*vn, vn^2]``；对广角畸变有吸收能力。"""
    points = np.asarray(normalized_uv, dtype=float)
    un, vn = points[:, 0], points[:, 1]
    return np.stack([np.ones_like(un), un, vn, un * un, un * vn, vn * vn], axis=1)


def solve_homography(image_uv: np.ndarray, workspace_xy: np.ndarray) -> tuple[np.ndarray, ImageNormalization]:
    """用归一化 DLT 求 3x3 单应矩阵 H，使 ``[x, y, 1] ~ H [u, v, 1]``。

    归一化（Hartley）是数值条件数要求，不是精度妥协：像素量级 ~300，其平方量级
    会直接毁掉最小二乘。至少需要 4 个点，实际应给 ≥6 个铺开的点。
    """
    points = np.asarray(image_uv, dtype=float)
    targets = np.asarray(workspace_xy, dtype=float)
    if len(points) < 4:
        raise ValueError("homography requires at least 4 calibration points")

    normalization = ImageNormalization.from_points(points)
    src = normalization.apply(points)
    wc = targets.mean(axis=0)
    shifted = targets - wc
    workspace_scale = float(np.sqrt((shifted ** 2).sum(axis=1)).mean())
    if not np.isfinite(workspace_scale) or workspace_scale <= 0:
        raise ValueError("workspace points are degenerate")
    dst = shifted / workspace_scale

    rows = np.zeros((2 * len(src), 9), dtype=float)
    for index, ((u, v), (x, y)) in enumerate(zip(src, dst, strict=True)):
        rows[2 * index] = [u, v, 1.0, 0.0, 0.0, 0.0, -u * x, -v * x, -x]
        rows[2 * index + 1] = [0.0, 0.0, 0.0, u, v, 1.0, -u * y, -v * y, -y]
    _, singular, vt = np.linalg.svd(rows)
    # 需要 rank(A) == 8（零空间恰好一维）。第 8 个奇异值（索引 7）为 0 就是退化：
    # 共线布点会让解不唯一，此时不能假装出了一张标定表。
    if singular[7] <= 0.0 or singular[7] / singular[0] < 1e-12:
        raise ValueError("degenerate homography; calibration points must not be collinear")
    normalized_h = vt[-1].reshape(3, 3)

    to_normalized = np.array(
        [
            [1.0 / normalization.scale, 0.0, -normalization.cu / normalization.scale],
            [0.0, 1.0 / normalization.scale, -normalization.cv / normalization.scale],
            [0.0, 0.0, 1.0],
        ]
    )
    from_normalized = np.array(
        [
            [workspace_scale, 0.0, wc[0]],
            [0.0, workspace_scale, wc[1]],
            [0.0, 0.0, 1.0],
        ]
    )
    matrix = from_normalized @ normalized_h @ to_normalized
    norm = float(np.linalg.norm(matrix))
    if not np.isfinite(norm) or norm < 1e-12:
        raise ValueError("degenerate homography; check that points are not collinear")
    return matrix / norm, normalization


def solve_poly2(image_uv: np.ndarray, workspace_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray, ImageNormalization]:
    """对每轴各拟合一个二次多项式 ``[1, un, vn, un^2, un*vn, vn^2]``。

    这是文档里"中央区域双线性插值"的等价替代：双线性只在规则 3x3 网格上自然，
    而二次多项式对非规则布点同样成立，且能吸收广角镜头在平面上的低阶畸变。
    至少需要 6 个点。
    """
    points = np.asarray(image_uv, dtype=float)
    targets = np.asarray(workspace_xy, dtype=float)
    if len(points) < POLY_BASIS_SIZE:
        raise ValueError(f"poly2 requires at least {POLY_BASIS_SIZE} calibration points")
    normalization = ImageNormalization.from_points(points)
    basis = _poly_basis(normalization.apply(points))
    x_coefficients, *_ = np.linalg.lstsq(basis, targets[:, 0], rcond=None)
    y_coefficients, *_ = np.linalg.lstsq(basis, targets[:, 1], rcond=None)
    return x_coefficients, y_coefficients, normalization


# --------------------------------------------------------------------------
# 有效性边界：凸包
# --------------------------------------------------------------------------


def convex_hull(image_uv: np.ndarray) -> list[list[float]]:
    """Andrew 单调链求凸包，返回逆时针顶点；共线点被剔除。"""
    unique = sorted({(float(u), float(v)) for u, v in np.asarray(image_uv, dtype=float)})
    if len(unique) <= 2:
        return [[u, v] for u, v in unique]

    def cross(origin, first, second) -> float:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    return [[float(u), float(v)] for u, v in hull]


def point_in_convex_polygon(point_uv, hull, margin_px: float = 0.0) -> bool:
    """判断点是否落在凸包内；``margin_px > 0`` 时要求离每条边至少这么远。

    凸包逆时针，内部在每条有向边的左侧。边距余量用来避免在边界上映射——
    那里已是被验证区域的边缘，继续使用等于在用外推冒充内插。
    """
    if hull is None or len(hull) < 3:
        return False
    point = np.asarray(point_uv, dtype=float)
    polygon = np.asarray(hull, dtype=float)
    for index in range(len(polygon)):
        start = polygon[index]
        end = polygon[(index + 1) % len(polygon)]
        edge = end - start
        signed = edge[0] * (point[1] - start[1]) - edge[1] * (point[0] - start[0])
        if margin_px > 0.0:
            length = float(np.hypot(edge[0], edge[1]))
            if length <= 0:
                continue
            if signed / length < margin_px:
                return False
        elif signed < 0:
            return False
    return True


# --------------------------------------------------------------------------
# 映射对象
# --------------------------------------------------------------------------


class PlaneMapping:
    """固定平面上的像素 -> 毫米映射，含拟合模型、配置元数据与有效性边界。"""

    def __init__(
        self,
        *,
        method: str,
        normalization: ImageNormalization,
        hull_uv: list[list[float]],
        margin_px: float,
        points: list[CalibrationPoint],
        metadata: dict,
        matrix: np.ndarray | None = None,
        x_coefficients: np.ndarray | None = None,
        y_coefficients: np.ndarray | None = None,
        validation: ValidationReport | None = None,
    ) -> None:
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")
        if method == "homography" and matrix is None:
            raise ValueError("homography method needs a 3x3 matrix")
        if method == "poly2" and (x_coefficients is None or y_coefficients is None):
            raise ValueError("poly2 method needs both coefficient vectors")
        self.method = method
        self.normalization = normalization
        self.hull_uv = hull_uv
        self.margin_px = float(margin_px)
        self.points = list(points)
        self.metadata = dict(metadata)
        self.matrix = None if matrix is None else np.asarray(matrix, dtype=float)
        self.x_coefficients = None if x_coefficients is None else np.asarray(x_coefficients, dtype=float)
        self.y_coefficients = None if y_coefficients is None else np.asarray(y_coefficients, dtype=float)
        self.validation = validation

    @classmethod
    def fit(
        cls,
        points: list[CalibrationPoint],
        *,
        method: str = "homography",
        margin_px: float = DEFAULT_MARGIN_PX,
        metadata: dict | None = None,
    ) -> "PlaneMapping":
        """只用 ``split == 'calibrate'`` 的点求解；验证点仅用于事后报误差。"""
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")
        calibrate = [point for point in points if point.split == "calibrate"]
        if not calibrate:
            raise ValueError("no calibration points (split='calibrate') were provided")
        image_uv = np.array([[point.u, point.v] for point in calibrate], dtype=float)
        workspace_xy = np.array([[point.x_mm, point.y_mm] for point in calibrate], dtype=float)

        matrix = x_coefficients = y_coefficients = None
        if method == "homography":
            matrix, normalization = solve_homography(image_uv, workspace_xy)
        else:
            x_coefficients, y_coefficients, normalization = solve_poly2(image_uv, workspace_xy)

        all_uv = np.array([[point.u, point.v] for point in points], dtype=float)
        mapping = cls(
            method=method,
            normalization=normalization,
            hull_uv=convex_hull(all_uv),
            margin_px=margin_px,
            points=points,
            metadata=metadata or {},
            matrix=matrix,
            x_coefficients=x_coefficients,
            y_coefficients=y_coefficients,
        )
        mapping.validation = mapping.evaluate(points)
        return mapping

    def _normalized(self, u: float, v: float) -> tuple[float, float]:
        un = (u - self.normalization.cu) / self.normalization.scale
        vn = (v - self.normalization.cv) / self.normalization.scale
        return float(un), float(vn)

    def map_point(self, u: float, v: float) -> tuple[float, float]:
        """把像素中心映射为工作平面毫米坐标；不做有效性检查，调用方自负。"""
        if self.method == "homography":
            vector = self.matrix @ np.array([u, v, 1.0])
            denominator = float(vector[2])
            if abs(denominator) < 1e-12:
                raise ValueError("point maps to infinity for this homography")
            return float(vector[0] / denominator), float(vector[1] / denominator)
        un, vn = self._normalized(u, v)
        basis = _poly_basis(np.array([[un, vn]], dtype=float))[0]
        return float(basis @ self.x_coefficients), float(basis @ self.y_coefficients)

    def contains(self, u: float, v: float) -> bool:
        """目标是否落在已验证点的凸包内（含设定的边距余量）。"""
        return point_in_convex_polygon((u, v), self.hull_uv, self.margin_px)

    def local_scale_mm_per_px(self, u: float, v: float, *, delta: float = 1.0) -> float:
        """该像素邻域内 1 像素对应多少毫米。

        取映射雅可比的几何平均（sqrt|det J|）：它对两个方向的缩放做几何平均，
        因此不受旋转或轻微剪切影响，适合回答"当前分辨率够不够"。
        用有限差分实现，对 homography 与 poly2 同一套逻辑。
        """
        origin_x, origin_y = self.map_point(u, v)
        step_u_x, step_u_y = self.map_point(u + delta, v)
        step_v_x, step_v_y = self.map_point(u, v + delta)
        column_u = ((step_u_x - origin_x) / delta, (step_u_y - origin_y) / delta)
        column_v = ((step_v_x - origin_x) / delta, (step_v_y - origin_y) / delta)
        determinant = column_u[0] * column_v[1] - column_u[1] * column_v[0]
        return float(np.sqrt(abs(determinant)))

    def pixel_scale_report(self) -> dict:
        """在标定点质心处报告像素尺度，并判断能否支撑毫米级定位。

        这不是标定精度本身，而是精度上限：1 像素误差会放大成多少毫米。
        相机架得越高、视场角越宽，这个值越差。
        """
        calibrate = [point for point in self.points if point.split == "calibrate"] or self.points
        if not calibrate:
            return {"at_uv": None, "mm_per_px": None, "px_per_mm": None, "enough_for_2mm": False}
        center_u = float(np.mean([point.u for point in calibrate]))
        center_v = float(np.mean([point.v for point in calibrate]))
        mm_per_px = self.local_scale_mm_per_px(center_u, center_v)
        px_per_mm = 0.0 if mm_per_px <= 0 else 1.0 / mm_per_px
        return {
            "at_uv": [center_u, center_v],
            "mm_per_px": mm_per_px,
            "px_per_mm": px_per_mm,
            "enough_for_2mm": px_per_mm >= ENOUGH_PX_PER_MM,
        }

    def map_point_checked(self, u: float, v: float) -> tuple[float, float] | None:
        """凸包外返回 ``None``（拒绝转换），不静默外推。"""
        if not self.contains(u, v):
            return None
        return self.map_point(u, v)

    def evaluate(self, points: list[CalibrationPoint]) -> ValidationReport:
        """逐点算残差，并按校准/验证两侧分别汇总。"""
        calibrate_errors: list[float] = []
        validate_errors: list[float] = []
        per_point: list[PointError] = []
        for point in points:
            mapped_x, mapped_y = self.map_point(point.u, point.v)
            error = float(np.hypot(mapped_x - point.x_mm, mapped_y - point.y_mm))
            per_point.append(PointError(name=point.name, split=point.split, error_mm=error))
            (calibrate_errors if point.split == "calibrate" else validate_errors).append(error)
        calibrate_mean, calibrate_rms, calibrate_max = _summarize(calibrate_errors)
        validate_mean, validate_rms, validate_max = _summarize(validate_errors)
        return ValidationReport(
            n_calibrate=len(calibrate_errors),
            n_validate=len(validate_errors),
            calibrate_mean_mm=calibrate_mean,
            calibrate_rms_mm=calibrate_rms,
            calibrate_max_mm=calibrate_max,
            validate_mean_mm=validate_mean,
            validate_rms_mm=validate_rms,
            validate_max_mm=validate_max,
            points=tuple(per_point),
        )

    def to_dict(self) -> dict:
        """序列化为可写入 YAML 的字典；不含任何伪造的毫米常量。"""
        data = {
            "schema": SCHEMA_VERSION,
            "method": self.method,
            "image_normalization": {
                "cu": float(self.normalization.cu),
                "cv": float(self.normalization.cv),
                "scale": float(self.normalization.scale),
            },
            "valid_region": {
                "hull_uv": [[float(u), float(v)] for u, v in self.hull_uv],
                "margin_px": float(self.margin_px),
            },
            "calibration_points": [point.to_dict() for point in self.points],
            "validation": None if self.validation is None else self.validation.to_dict(),
            "metadata": dict(self.metadata),
        }
        if self.method == "homography":
            data["matrix"] = [[float(value) for value in row] for row in self.matrix.tolist()]
        else:
            data["x_coefficients"] = [float(value) for value in self.x_coefficients.tolist()]
            data["y_coefficients"] = [float(value) for value in self.y_coefficients.tolist()]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PlaneMapping":
        """从配置字典恢复映射；缺字段或 schema 不符时明确报错。"""
        if int(data.get("schema", 0)) != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema: {data.get('schema')}")
        method = str(data["method"])
        raw_normalization = data["image_normalization"]
        normalization = ImageNormalization(
            cu=float(raw_normalization["cu"]),
            cv=float(raw_normalization["cv"]),
            scale=float(raw_normalization["scale"]),
        )
        region = data["valid_region"]
        points = [
            CalibrationPoint(
                name=str(item["name"]),
                u=float(item["u"]),
                v=float(item["v"]),
                x_mm=float(item["x_mm"]),
                y_mm=float(item["y_mm"]),
                split=str(item.get("split", "calibrate")),
            )
            for item in data.get("calibration_points", [])
        ]
        matrix = np.array(data["matrix"], dtype=float) if method == "homography" else None
        x_coefficients = np.array(data["x_coefficients"], dtype=float) if method == "poly2" else None
        y_coefficients = np.array(data["y_coefficients"], dtype=float) if method == "poly2" else None
        return cls(
            method=method,
            normalization=normalization,
            hull_uv=[[float(u), float(v)] for u, v in region["hull_uv"]],
            margin_px=float(region.get("margin_px", DEFAULT_MARGIN_PX)),
            points=points,
            metadata=dict(data.get("metadata", {})),
            matrix=matrix,
            x_coefficients=x_coefficients,
            y_coefficients=y_coefficients,
        )

    def save(self, path: Path) -> None:
        """写出映射配置；写入失败直接抛错，不生成半截文件。"""
        import yaml

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(
            self.to_dict(), allow_unicode=True, sort_keys=False, default_flow_style=False
        )
        path.write_text(text, encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "PlaneMapping":
        """读取映射配置，并立刻用自带点对复算残差，防止配置被手改坏。"""
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        mapping = cls.from_dict(data)
        if mapping.points:
            mapping.validation = mapping.evaluate(mapping.points)
        return mapping


# --------------------------------------------------------------------------
# 点对 CSV
# --------------------------------------------------------------------------


def write_points_csv(path: Path, points: list[CalibrationPoint], extra_rows: list[dict] | None = None) -> None:
    """写出点对 CSV；``extra_rows`` 携带采集时的检出诊断，可缺省。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics = {(row["name"]): row for row in (extra_rows or [])}
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for point in points:
            row = point.to_dict()
            row["detections"] = diagnostics.get(point.name, {}).get("detections", "")
            row["confidence"] = diagnostics.get(point.name, {}).get("confidence", "")
            writer.writerow(row)


def load_points_csv(path: Path) -> list[CalibrationPoint]:
    """读取点对 CSV；只依赖 name/u/v/x_mm/y_mm/split，其余列被忽略。"""
    points: list[CalibrationPoint] = []
    with Path(path).open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if not row or not (row.get("name") or "").strip():
                continue
            points.append(
                CalibrationPoint(
                    name=str(row["name"]).strip(),
                    u=float(row["u"]),
                    v=float(row["v"]),
                    x_mm=float(row["x_mm"]),
                    y_mm=float(row["y_mm"]),
                    split=(row.get("split") or "calibrate").strip() or "calibrate",
                )
            )
    if not points:
        raise ValueError(f"no usable point pairs in {path}")
    return points


# --------------------------------------------------------------------------
# 阶段一：采集点对（用现有 YOLO，不引入第二套检测器）
# --------------------------------------------------------------------------


def _read_image(path: Path) -> np.ndarray:
    """读取支持 Unicode 路径的图片并返回 BGR 数组。"""
    import cv2

    encoded = np.fromfile(path, dtype=np.uint8)
    frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cannot decode image: {path}")
    return frame


def collect_points(
    images_dir: Path,
    output_csv: Path,
    *,
    weights: Path,
    confidence: float,
    imgsz: int,
    device: str,
) -> list[CalibrationPoint]:
    """把 ``x坐标_y坐标_序号.png`` 形式的实拍图跑 YOLO，导出像素中心点对。

    文件名给出已知工作坐标；检出框给出像素中心。若某帧不是恰好一个目标，会被计入
    诊断列而不是悄悄补一个坐标，让操作者在 CSV 里就能看出哪几个点可疑。
    """
    from .yolo_inference import IsolatedYoloInference

    images = sorted(
        path for path in Path(images_dir).iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not images:
        raise ValueError(f"no supported images in {images_dir}")

    engine = IsolatedYoloInference(weights, confidence=confidence, imgsz=imgsz, device=device)
    points: list[CalibrationPoint] = []
    diagnostics: list[dict] = []
    for frame_index, image_path in enumerate(images):
        match = POINT_IMAGE_PATTERN.match(image_path.stem)
        if match is None:
            print(f"[skip] 文件名不是 <x>_<y>_<seq>: {image_path.name}")
            continue
        x_mm, y_mm = float(match.group(1)), float(match.group(2))
        record, _ = engine.infer_frame(
            _read_image(image_path),
            source=str(image_path.resolve()),
            frame_index=frame_index,
            timestamp_s=None,
            timestamp_kind="not_available_for_still_image",
        )
        if not record.detections:
            print(f"[skip] 无检出: {image_path.name}")
            continue
        best = max(record.detections, key=lambda item: item.confidence)
        if len(record.detections) != 1:
            print(f"[warn] {image_path.name} 检出 {len(record.detections)} 个目标，取置信度最高者")
        points.append(
            CalibrationPoint(
                name=image_path.stem, u=best.center_px[0], v=best.center_px[1],
                x_mm=x_mm, y_mm=y_mm, split="calibrate",
            )
        )
        diagnostics.append(
            {"name": image_path.stem, "detections": len(record.detections), "confidence": round(best.confidence, 4)}
        )
    if not points:
        raise ValueError("no point pairs were produced from the image directory")
    write_points_csv(output_csv, points, diagnostics)
    return points


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _print_report(mapping: PlaneMapping, max_error_mm: float) -> None:
    """打印逐点残差与汇总；这是校准是否可用的唯一判据。"""
    report = mapping.validation
    if report is None:
        return
    print(f"{'name':<28}{'split':<11}{'error_mm':>10}")
    for point in report.points:
        print(f"{point.name:<28}{point.split:<11}{point.error_mm:>10.3f}")
    print("-" * 49)
    print(
        f"calibrate   n={report.n_calibrate}  "
        f"mean={report.calibrate_mean_mm:.3f}  rms={report.calibrate_rms_mm:.3f}  max={report.calibrate_max_mm:.3f} mm"
    )
    if report.n_validate:
        print(
            f"validate    n={report.n_validate}  "
            f"mean={report.validate_mean_mm:.3f}  rms={report.validate_rms_mm:.3f}  max={report.validate_max_mm:.3f} mm"
        )
    else:
        print("validate    n=0  —— 没有独立验证点，不能判定通过")
    verdict = "PASS" if report.passed(max_error_mm) else "FAIL"
    print(f"threshold max_error_mm={max_error_mm} -> {verdict}")
    scale = mapping.pixel_scale_report()
    if scale["mm_per_px"] is not None:
        print(
            f"pixel scale  {scale['px_per_mm']:.2f} px/mm "
            f"(1 px = {scale['mm_per_px']:.3f} mm) at u,v={scale['at_uv'][0]:.1f},{scale['at_uv'][1]:.1f}"
        )
        if not scale["enough_for_2mm"]:
            print(
                f"  [warn] 像素尺度低于 {ENOUGH_PX_PER_MM:.1f} px/mm：1 像素已接近定位误差预算，"
                "先解决分辨率（缩小视场角 / 提高分辨率 / 降低相机高度），不要靠调参硬凑。"
            )


def _build_parser() -> argparse.ArgumentParser:
    """构造 collect / calibrate / map 三个子命令。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="把实拍图跑 YOLO 导出点对 CSV")
    collect.add_argument("--images-dir", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    collect.add_argument("--conf", type=float, default=0.25)
    collect.add_argument("--imgsz", type=int, default=640)
    collect.add_argument("--device", default="0")

    calibrate = sub.add_parser("calibrate", help="用点对求映射并写出配置")
    calibrate.add_argument("--points", type=Path, required=True)
    calibrate.add_argument("--output", type=Path, required=True)
    calibrate.add_argument("--method", choices=METHODS, default="homography")
    calibrate.add_argument("--margin-px", type=float, default=DEFAULT_MARGIN_PX)
    calibrate.add_argument("--max-error-mm", type=float, default=DEFAULT_MAX_ERROR_MM)
    calibrate.add_argument("--workspace-id", default="")
    calibrate.add_argument("--resolution", default="", help="形如 640x480，写入元数据")
    calibrate.add_argument("--background", default="", help="yellow_desk / green_belt")
    calibrate.add_argument("--camera-index", type=int, default=-1)
    calibrate.add_argument("--note", default="")

    runtime = sub.add_parser("map", help="运行时把像素映射为毫米")
    runtime.add_argument("--config", type=Path, required=True)
    runtime.add_argument("--u", type=float, required=True)
    runtime.add_argument("--v", type=float, required=True)
    return parser


def _run_calibrate(args: argparse.Namespace) -> int:
    """求解并写配置；独立验证点缺失或超阈值时返回非零退出码。"""
    points = load_points_csv(args.points)
    metadata = {
        "workspace_id": args.workspace_id,
        "resolution": args.resolution,
        "background": args.background,
        "camera_index": None if args.camera_index < 0 else args.camera_index,
        "note": args.note,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    mapping = PlaneMapping.fit(points, method=args.method, margin_px=args.margin_px, metadata=metadata)
    _print_report(mapping, args.max_error_mm)
    mapping.save(args.output)
    print(f"wrote {args.output}")
    return 0 if mapping.validation.passed(args.max_error_mm) else 1


def _run_map(args: argparse.Namespace) -> int:
    """运行时映射；凸包外拒绝转换并返回非零退出码。"""
    mapping = PlaneMapping.load(args.config)
    result = mapping.map_point_checked(args.u, args.v)
    payload = {
        "method": mapping.method,
        "u": args.u,
        "v": args.v,
        "inside_valid_region": result is not None,
        "x_mm": None if result is None else result[0],
        "y_mm": None if result is None else result[1],
    }
    print(json.dumps(payload, ensure_ascii=False))
    if result is None:
        print("目标在已验证凸包外：拒绝转换，不外推。", flush=True)
        return 1
    return 0


def main(argv=None) -> int:
    """解析子命令并分派；返回进程退出码。"""
    args = _build_parser().parse_args(argv)
    if args.command == "collect":
        points = collect_points(
            args.images_dir, args.output, weights=args.weights,
            confidence=args.conf, imgsz=args.imgsz, device=args.device,
        )
        print(f"collected {len(points)} point pairs -> {args.output}")
        return 0
    if args.command == "calibrate":
        return _run_calibrate(args)
    return _run_map(args)


if __name__ == "__main__":
    raise SystemExit(main())
