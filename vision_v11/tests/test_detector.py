"""模型与摄像头测试：纯逻辑单元测试加可用环境的真实权重检查。"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from vision.camera import Camera
from vision.detector import DEFAULT_MODEL, Detector


class DetectorTests(unittest.TestCase):
    def test_relative_model_path(self):
        self.assertEqual(DEFAULT_MODEL, Path(__file__).resolve().parents[1] / "models" / "best.pt")

    def test_weight_and_class_mapping(self):
        detector = Detector(device="cpu")
        self.assertEqual({int(k): v for k, v in detector.model.names.items()},
                         {0: "cube", 1: "cylinder"})

    def test_cpu_blank_frame(self):
        detector = Detector(device="cpu")
        result = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual((result.frame_width, result.frame_height), (640, 480))
        self.assertIsInstance(result.detections, tuple)

    def test_invalid_frame(self):
        detector = Detector(device="cpu")
        with self.assertRaises(ValueError):
            detector.detect(None)

    def test_camera_release(self):
        fake = SimpleNamespace(isOpened=lambda: True, set=lambda *_: True,
                               read=lambda: (True, np.zeros((480, 640, 3), dtype=np.uint8)),
                               release=unittest.mock.Mock())
        with patch("vision.camera.cv2.VideoCapture", return_value=fake):
            with Camera(index=1) as camera:
                self.assertEqual(camera.read().shape, (480, 640, 3))
        fake.release.assert_called_once()

    def test_camera_failure_releases(self):
        fake = SimpleNamespace(isOpened=lambda: False, release=unittest.mock.Mock())
        with patch("vision.camera.cv2.VideoCapture", return_value=fake):
            with self.assertRaises(RuntimeError):
                Camera(index=1).open()
        fake.release.assert_called_once()
