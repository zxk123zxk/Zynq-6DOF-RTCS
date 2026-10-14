"""``src.vision.plane_mapping`` 的离线单元测试。

这些测试只用合成几何构造点对，不访问相机、不加载 YOLO 权重、不驱动机械臂。
它们验证的是"求解正确、验证点独立、越界拒绝"这三条契约，不代表现场定位精度。
"""
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import numpy as np

from src.vision.plane_mapping import (
    CalibrationPoint,
    ImageNormalization,
    PlaneMapping,
    convex_hull,
    load_points_csv,
    point_in_convex_polygon,
    solve_homography,
    solve_poly2,
    write_points_csv,
)
# 一套铺开的像素采样点（模拟 640x480 画面中央区域）。
PIXEL_GRID = [
    (100.0, 120.0), (300.0, 120.0), (500.0, 120.0),
    (100.0, 250.0), (300.0, 250.0), (500.0, 250.0),
    (100.0, 380.0), (300.0, 380.0), (500.0, 380.0),
]

# 一个带透视项的已知单应（0.5 mm/px 量级 + 小透视扰动）。
KNOWN_HOMOGRAPHY = np.array(
    [
        [0.5000, 0.0100, -60.0],
        [0.0050, 0.5100, -55.0],
        [0.0002, 0.0003, 1.0],
    ]
)


def homography_points() -> list[tuple[float, float, float, float]]:
    """按已知单应生成 (u, v, x_mm, y_mm)；作为求解真值。"""
    pairs = []
    for u, v in PIXEL_GRID:
        vector = KNOWN_HOMOGRAPHY @ np.array([u, v, 1.0])
        pairs.append((u, v, float(vector[0] / vector[2]), float(vector[1] / vector[2])))
    return pairs


def make_points(rows, split: str = "calibrate", prefix: str = "p") -> list[CalibrationPoint]:
    """把 (u, v, x, y) 元组列表转成标定点。"""
    return [
        CalibrationPoint(name=f"{prefix}{index}", u=u, v=v, x_mm=x, y_mm=y, split=split)
        for index, (u, v, x, y) in enumerate(rows)
    ]


class CalibrationPointTests(unittest.TestCase):
    """标定点的字段契约。"""

    def test_rejects_unknown_split(self) -> None:
        with self.assertRaises(ValueError):
            CalibrationPoint(name="a", u=1.0, v=1.0, x_mm=1.0, y_mm=1.0, split="train")

    def test_rejects_non_finite_coordinate(self) -> None:
        with self.assertRaises(ValueError):
            CalibrationPoint(name="a", u=float("nan"), v=1.0, x_mm=1.0, y_mm=1.0)

    def test_rejects_empty_name(self) -> None:
        with self.assertRaises(ValueError):
            CalibrationPoint(name="", u=1.0, v=1.0, x_mm=1.0, y_mm=1.0)

    def test_to_dict_carries_all_fields(self) -> None:
        point = CalibrationPoint(name="p0", u=10.0, v=20.0, x_mm=5.0, y_mm=6.0, split="validate")
        self.assertEqual(
            point.to_dict(),
            {"name": "p0", "u": 10.0, "v": 20.0, "x_mm": 5.0, "y_mm": 6.0, "split": "validate"},
        )


class NormalizationTests(unittest.TestCase):
    """像素归一化必须居中、缩放有限。"""

    def test_centered_and_scaled(self) -> None:
        points = np.array(PIXEL_GRID, dtype=float)
        normalization = ImageNormalization.from_points(points)
        normalized = normalization.apply(points)
        self.assertAlmostEqual(float(normalized[:, 0].mean()), 0.0, places=9)
        self.assertAlmostEqual(float(normalized[:, 1].mean()), 0.0, places=9)
        self.assertGreater(normalization.scale, 0.0)

    def test_single_point_falls_back_to_unit_scale(self) -> None:
        normalization = ImageNormalization.from_points(np.array([[10.0, 10.0]]))
        self.assertEqual(normalization.scale, 1.0)


class HomographySolverTests(unittest.TestCase):
    """单应求解应精确还原已知真值。"""

    def test_recovers_known_homography(self) -> None:
        rows = homography_points()
        image_uv = np.array([[u, v] for u, v, _, _ in rows])
        workspace_xy = np.array([[x, y] for _, _, x, y in rows])
        matrix, _ = solve_homography(image_uv, workspace_xy)
        for u, v, x, y in rows:
            vector = matrix @ np.array([u, v, 1.0])
            self.assertAlmostEqual(float(vector[0] / vector[2]), x, places=6)
            self.assertAlmostEqual(float(vector[1] / vector[2]), y, places=6)

    def test_requires_four_points(self) -> None:
        with self.assertRaises(ValueError):
            solve_homography(np.zeros((3, 2)), np.zeros((3, 2)))

    def test_rejects_collinear_points(self) -> None:
        image_uv = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
        workspace_xy = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
        with self.assertRaises(ValueError):
            solve_homography(image_uv, workspace_xy)


class Poly2SolverTests(unittest.TestCase):
    """二次多项式应精确还原二次真值，并拒绝点数不足。"""

    def test_recovers_quadratic_truth(self) -> None:
        rows = []
        for u, v in PIXEL_GRID:
            x = 2.0 + 0.5 * u - 0.1 * v + 1e-4 * u * u + 2e-4 * u * v - 3e-4 * v * v
            y = -30.0 + 0.05 * u + 0.6 * v - 2e-4 * u * u + 1e-4 * u * v + 5e-5 * v * v
            rows.append((u, v, x, y))
        image_uv = np.array([[u, v] for u, v, _, _ in rows])
        workspace_xy = np.array([[x, y] for _, _, x, y in rows])
        x_coefficients, y_coefficients, normalization = solve_poly2(image_uv, workspace_xy)
        for u, v, x, y in rows:
            un = (u - normalization.cu) / normalization.scale
            vn = (v - normalization.cv) / normalization.scale
            basis = np.array([1.0, un, vn, un * un, un * vn, vn * vn])
            self.assertAlmostEqual(float(basis @ x_coefficients), x, places=6)
            self.assertAlmostEqual(float(basis @ y_coefficients), y, places=6)

    def test_requires_six_points(self) -> None:
        with self.assertRaises(ValueError):
            solve_poly2(np.zeros((5, 2)), np.zeros((5, 2)))


class ConvexHullTests(unittest.TestCase):
    """凸包与越界判定。"""

    def test_square_hull_is_ccw_without_collinear_points(self) -> None:
        hull = convex_hull([[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0], [0, 0.5]])
        self.assertEqual(len(hull), 4)
        self.assertIn([0.0, 0.0], hull)
        self.assertIn([1.0, 1.0], hull)

    def test_degenerate_hull_below_three_points(self) -> None:
        self.assertFalse(point_in_convex_polygon((0.0, 0.0), convex_hull([[0, 0], [1, 1]])))

    def test_inside_outside_and_margin(self) -> None:
        hull = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
        self.assertTrue(point_in_convex_polygon((5.0, 5.0), hull))
        self.assertFalse(point_in_convex_polygon((11.0, 5.0), hull))
        self.assertFalse(point_in_convex_polygon((0.5, 5.0), hull, margin_px=1.0))
        self.assertTrue(point_in_convex_polygon((5.0, 5.0), hull, margin_px=1.0))


class PlaneMappingTests(unittest.TestCase):
    """映射对象的拟合、验证分离与越界拒绝。"""

    def test_fit_uses_calibrate_points_only(self) -> None:
        points = make_points(homography_points())
        reference = PlaneMapping.fit(points)
        contaminated = PlaneMapping.fit(
            points + make_points([(0.0, 0.0, 999.0, 999.0)], split="validate", prefix="v")
        )
        np.testing.assert_allclose(reference.matrix, contaminated.matrix, rtol=0, atol=1e-12)

    def test_fit_reports_zero_error_on_exact_truth(self) -> None:
        mapping = PlaneMapping.fit(make_points(homography_points()))
        self.assertLess(mapping.validation.calibrate_max_mm, 1e-6)

    def test_validate_max_error_is_separate_from_calibrate(self) -> None:
        calibrate = make_points(homography_points())
        # 故意给一个错误的验证点，验证误差必须体现在 validate 一侧。
        validate = make_points([(300.0, 250.0, 999.0, 999.0)], split="validate", prefix="v")
        mapping = PlaneMapping.fit(calibrate + validate)
        self.assertLess(mapping.validation.calibrate_max_mm, 1e-6)
        self.assertGreater(mapping.validation.validate_max_mm, 100.0)
        self.assertFalse(mapping.validation.passed(2.0))

    def test_requires_calibration_points(self) -> None:
        with self.assertRaises(ValueError):
            PlaneMapping.fit(make_points(homography_points(), split="validate"))

    def test_rejects_unknown_method(self) -> None:
        with self.assertRaises(ValueError):
            PlaneMapping.fit(make_points(homography_points()), method="bogus")

    def test_map_point_checked_refuses_outside_hull(self) -> None:
        mapping = PlaneMapping.fit(make_points(homography_points()))
        self.assertIsNotNone(mapping.map_point_checked(300.0, 250.0))
        self.assertIsNone(mapping.map_point_checked(5000.0, 5000.0))

    def test_poly2_mapping_matches_truth(self) -> None:
        rows = []
        for u, v in PIXEL_GRID:
            rows.append((u, v, 0.4 * u - 0.2 * v + 5.0, 0.1 * u + 0.55 * v - 8.0))
        mapping = PlaneMapping.fit(make_points(rows), method="poly2")
        self.assertLess(mapping.validation.calibrate_max_mm, 1e-6)
        self.assertEqual(mapping.method, "poly2")


class PersistenceTests(unittest.TestCase):
    """CSV 与 YAML 往返必须保真。"""

    def test_csv_round_trip_ignores_extra_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "points.csv"
            points = make_points(homography_points())
            write_points_csv(
                path, points, [{"name": "p0", "detections": 1, "confidence": 0.9}]
            )
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\n")
            loaded = load_points_csv(path)
            self.assertEqual([p.to_dict() for p in loaded], [p.to_dict() for p in points])

    def test_empty_csv_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            path.write_text("name,u,v,x_mm,y_mm,split\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_points_csv(path)

    def test_yaml_round_trip_preserves_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace_plane.yaml"
            mapping = PlaneMapping.fit(
                make_points(homography_points()), metadata={"workspace_id": "demo"}
            )
            mapping.save(path)
            restored = PlaneMapping.load(path)
            self.assertEqual(restored.method, mapping.method)
            self.assertEqual(restored.metadata["workspace_id"], "demo")
            np.testing.assert_allclose(restored.map_point(300.0, 250.0), mapping.map_point(300.0, 250.0))
            self.assertLess(restored.validation.calibrate_max_mm, 1e-6)
            self.assertEqual(restored.hull_uv, mapping.hull_uv)

    def test_from_dict_rejects_wrong_schema(self) -> None:
        with self.assertRaises(ValueError):
            PlaneMapping.from_dict({"schema": 99})


class PixelScaleTests(unittest.TestCase):
    """像素尺度：它决定定位精度的上限，不是标定误差本身。"""

    def test_known_homography_gives_expected_scale(self) -> None:
        # KNOWN_HOMOGRAPHY 约为 0.5 mm/px，质心 (300,250) 处的分母 1.135 会把它压到约 0.43。
        mapping = PlaneMapping.fit(make_points(homography_points()))
        report = mapping.pixel_scale_report()
        self.assertEqual(report["at_uv"], [300.0, 250.0])
        self.assertAlmostEqual(report["mm_per_px"], 0.43, delta=0.02)
        self.assertAlmostEqual(report["px_per_mm"], 1.0 / report["mm_per_px"], places=9)
        self.assertTrue(report["enough_for_2mm"])

    def test_wide_scale_is_flagged_not_enough(self) -> None:
        # 同一个单应整体放大一倍 => 1 像素代表约 0.86 mm => 低于 2 px/mm 门槛。
        doubled = make_points(
            [(u, v, x * 2.0, y * 2.0) for u, v, x, y in homography_points()]
        )
        report = PlaneMapping.fit(doubled).pixel_scale_report()
        self.assertLess(report["px_per_mm"], 2.0)
        self.assertFalse(report["enough_for_2mm"])

    def test_poly2_scale_matches_uniform_truth(self) -> None:
        rows = [(u, v, 0.4 * (u - 300.0), 0.4 * (v - 250.0)) for u, v in PIXEL_GRID]
        report = PlaneMapping.fit(make_points(rows), method="poly2").pixel_scale_report()
        self.assertAlmostEqual(report["mm_per_px"], 0.4, delta=1e-6)
        self.assertAlmostEqual(report["px_per_mm"], 2.5, delta=1e-6)

    def test_scale_is_isotropic_under_pure_scaling(self) -> None:
        mapping = PlaneMapping.fit(make_points(homography_points()))
        center = mapping.local_scale_mm_per_px(300.0, 250.0)
        corner = mapping.local_scale_mm_per_px(100.0, 120.0)
        self.assertGreater(center, 0.0)
        self.assertGreater(corner, 0.0)
        self.assertLess(abs(center - corner), 0.15)

    def test_report_without_points_is_invalid_not_zero(self) -> None:
        mapping = PlaneMapping(
            method="homography",
            normalization=ImageNormalization(cu=0.0, cv=0.0, scale=1.0),
            hull_uv=[],
            margin_px=0.0,
            points=[],
            metadata={},
            matrix=np.eye(3),
        )
        report = mapping.pixel_scale_report()
        self.assertIsNone(report["mm_per_px"])
        self.assertFalse(report["enough_for_2mm"])


if __name__ == "__main__":
    unittest.main()
