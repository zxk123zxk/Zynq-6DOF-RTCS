"""不依赖摄像头的结果契约测试。"""
import unittest

from vision.results import Detection, FrameResult


class ResultsTests(unittest.TestCase):
    def test_center_and_class(self):
        item = Detection.from_bbox(0, 0.8, (10, 20, 30, 40), 640, 480)
        self.assertEqual((item.class_name, item.center_x, item.center_y), ("Cube", 20, 30))

    def test_clip_to_original_frame(self):
        item = Detection.from_bbox(1, 0.6, (-5, 10, 650, 500), 640, 480)
        self.assertEqual(item.bbox_xyxy, (0.0, 10, 640.0, 480.0))

    def test_invalid_bbox_and_class(self):
        for class_id, bbox in ((2, (1, 1, 2, 2)), (0, (4, 4, 2, 2)),
                               (0, (float("nan"), 0, 1, 1))):
            with self.subTest(class_id=class_id, bbox=bbox), self.assertRaises(ValueError):
                Detection.from_bbox(class_id, 0.5, bbox, 640, 480)

    def test_empty_frame(self):
        self.assertEqual(FrameResult(640, 480, ()).detections, ())
