# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import unittest

import numpy as np


from src.vision.yolo_inference import YoloFrameResult, detections_from_result


class FakeTensor:
    def __init__(self, array) -> None:
        self.array = np.asarray(array)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.array


class FakeBoxes:
    def __init__(self, xyxy, conf, cls) -> None:
        self.xyxy = FakeTensor(xyxy)
        self.conf = FakeTensor(conf)
        self.cls = FakeTensor(cls)


class FakeResult:
    def __init__(self, boxes) -> None:
        self.boxes = boxes


class YoloInferenceDataTest(unittest.TestCase):
    def test_detection_fields_and_center(self) -> None:
        result = FakeResult(FakeBoxes([[10, 20, 30, 60]], [0.8], [1]))
        detections = detections_from_result(result)
        self.assertEqual(len(detections), 1)
        detection = detections[0]
        self.assertIsInstance(detection.class_id, int)
        self.assertEqual(detection.class_id, 1)
        self.assertEqual(detection.class_name, "cylinder")
        self.assertEqual(detection.role, "anomaly")
        self.assertAlmostEqual(detection.confidence, 0.8, places=6)
        self.assertEqual(detection.bbox_xyxy, (10.0, 20.0, 30.0, 60.0))
        self.assertEqual(detection.center_px, (20.0, 40.0))

    def test_no_boxes_produces_empty_detection_list(self) -> None:
        self.assertEqual(detections_from_result(FakeResult(None)), ())

    def test_empty_frame_record_has_no_stale_coordinates(self) -> None:
        record = YoloFrameResult(
            source="test",
            frame_index=0,
            timestamp_s=None,
            timestamp_kind="not_available_for_still_image",
            processing_monotonic_timestamp_s=1.0,
            processing_latency_s=0.1,
            image_width_px=640,
            image_height_px=480,
            detections=(),
        )
        self.assertEqual(record.to_dict()["detections"], ())

    def test_unexpected_class_is_rejected(self) -> None:
        result = FakeResult(FakeBoxes([[0, 0, 1, 1]], [0.9], [2]))
        with self.assertRaisesRegex(ValueError, "unexpected class_id"):
            detections_from_result(result)


if __name__ == "__main__":
    unittest.main()
