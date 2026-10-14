"""``src.vision.camera_locking`` 的离线单元测试。

只测纯函数（设置解析、生效判定、基线比对），不打开任何相机、不访问硬件。
"""
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import argparse
import unittest

import numpy as np

from src.vision.camera_locking import (
    CONTROL_PROPERTIES,
    STATUS_APPLIED,
    STATUS_NOT_APPLIED,
    STATUS_UNKNOWN,
    _build_parser,
    classify_control,
    compare_frames,
    parse_setting,
)


class ParseSettingTests(unittest.TestCase):
    """``name=value`` 解析契约。"""

    def test_accepts_known_control(self) -> None:
        self.assertEqual(parse_setting("auto_exposure=1"), ("auto_exposure", 1.0))
        self.assertEqual(parse_setting("exposure=-6.0"), ("exposure", -6.0))

    def test_rejects_unknown_control(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_setting("turbo=1")

    def test_rejects_missing_separator(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_setting("auto_exposure")

    def test_rejects_non_numeric_value(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_setting("gain=high")

    def test_expected_controls_are_exposed(self) -> None:
        for name in ("auto_exposure", "exposure", "gain", "auto_wb", "wb_temperature"):
            self.assertIn(name, CONTROL_PROPERTIES)


class ClassifyControlTests(unittest.TestCase):
    """写成功不等于锁住：判定只看读回值。"""

    def test_applied_when_readback_matches(self) -> None:
        self.assertEqual(classify_control(1.0, 1.0), STATUS_APPLIED)

    def test_not_applied_when_readback_differs(self) -> None:
        self.assertEqual(classify_control(1.0, 0.75), STATUS_NOT_APPLIED)

    def test_unknown_when_readback_missing(self) -> None:
        self.assertEqual(classify_control(1.0, None), STATUS_UNKNOWN)

    def test_unknown_when_readback_not_finite(self) -> None:
        self.assertEqual(classify_control(1.0, float("nan")), STATUS_UNKNOWN)


class CompareFramesTests(unittest.TestCase):
    """基线比对的统计口径。"""

    def setUp(self) -> None:
        self.baseline = np.full((4, 4, 3), 100, dtype=np.uint8)

    def test_identical_frames_have_zero_change(self) -> None:
        result = compare_frames(self.baseline, self.baseline.copy())
        self.assertTrue(result["resolution_match"])
        self.assertEqual(result["mean_abs_diff"], 0.0)
        self.assertEqual(result["changed_pixel_ratio"], 0.0)

    def test_large_change_exceeds_threshold_everywhere(self) -> None:
        frame = np.full((4, 4, 3), 160, dtype=np.uint8)
        result = compare_frames(self.baseline, frame, pixel_threshold=12.0)
        self.assertAlmostEqual(result["mean_abs_diff"], 60.0)
        self.assertAlmostEqual(result["changed_pixel_ratio"], 1.0)

    def test_change_below_threshold_keeps_ratio_zero(self) -> None:
        frame = np.full((4, 4, 3), 105, dtype=np.uint8)
        result = compare_frames(self.baseline, frame, pixel_threshold=12.0)
        self.assertAlmostEqual(result["mean_abs_diff"], 5.0)
        self.assertAlmostEqual(result["changed_pixel_ratio"], 0.0)

    def test_threshold_is_exclusive_boundary(self) -> None:
        frame = np.full((4, 4, 3), 112, dtype=np.uint8)
        result = compare_frames(self.baseline, frame, pixel_threshold=12.0)
        self.assertAlmostEqual(result["changed_pixel_ratio"], 0.0)

    def test_resolution_mismatch_is_flagged_not_computed(self) -> None:
        result = compare_frames(self.baseline, np.zeros((5, 5, 3), dtype=np.uint8))
        self.assertFalse(result["resolution_match"])
        self.assertIsNone(result["changed_pixel_ratio"])
        self.assertIsNone(result["mean_abs_diff"])

    def test_grayscale_input_is_supported(self) -> None:
        baseline = np.full((3, 3), 10, dtype=np.uint8)
        frame = np.full((3, 3), 200, dtype=np.uint8)
        result = compare_frames(baseline, frame)
        self.assertTrue(result["resolution_match"])
        self.assertAlmostEqual(result["changed_pixel_ratio"], 1.0)


class ParserTests(unittest.TestCase):
    """CLI 契约。"""

    def test_defaults(self) -> None:
        args = _build_parser().parse_args([])
        self.assertEqual(args.camera_index, 1)
        self.assertEqual(args.backend, "auto")
        self.assertEqual(args.settings, [])

    def test_repeated_set_options_are_collected(self) -> None:
        args = _build_parser().parse_args(["--set", "auto_exposure=1", "--set", "gain=0"])
        self.assertEqual(args.settings, [("auto_exposure", 1.0), ("gain", 0.0)])

    def test_probe_flag(self) -> None:
        self.assertTrue(_build_parser().parse_args(["--probe"]).probe)


if __name__ == "__main__":
    unittest.main()
