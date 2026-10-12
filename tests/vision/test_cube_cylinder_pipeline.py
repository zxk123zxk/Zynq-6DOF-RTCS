# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import unittest

import cv2
import numpy as np

from src.vision.cube_cylinder_pipeline import (
    BackgroundDifferenceMaskConfig,
    ObjectDetection,
    OpenCVGeometryDetector,
    adapt_yolo_record,
)


def detector(*, roi=None) -> OpenCVGeometryDetector:
    return OpenCVGeometryDetector(
        BackgroundDifferenceMaskConfig(
            background_bgr=(30, 30, 30), distance_threshold=60, morphology_kernel_px=3
        ),
        roi_xyxy_px=roi,
    )


def controlled_frame() -> np.ndarray:
    frame = np.full((300, 500, 3), 30, dtype=np.uint8)
    square = cv2.boxPoints(((130, 150), (76, 76), 20)).astype(np.int32)
    cv2.fillConvexPoly(frame, square, (220, 220, 220), lineType=cv2.LINE_8)
    cv2.circle(frame, (350, 150), 42, (220, 220, 220), -1, lineType=cv2.LINE_8)
    return frame


class GeometryDetectorTest(unittest.TestCase):
    def test_two_objects_are_independent_and_classified(self) -> None:
        result, mask, diagnostics = detector().detect(
            controlled_frame(), frame_index=7, timestamp_s=1.25, timestamp_kind="video_media_timeline"
        )
        self.assertEqual([item.class_name for item in result.detections], ["cube", "cylinder"])
        self.assertEqual(len(result.detections), 2)
        self.assertEqual(result.frame_index, 7)
        self.assertEqual(result.timestamp_s, 1.25)
        self.assertEqual(mask.shape, (300, 500))
        self.assertEqual(sum(item.accepted for item in diagnostics), 2)
        self.assertAlmostEqual(result.detections[0].center_px[0], 130, delta=2)
        self.assertAlmostEqual(result.detections[1].center_px[0], 350, delta=2)

    def test_multiple_targets_are_all_returned(self) -> None:
        frame = np.full((300, 600, 3), 30, dtype=np.uint8)
        for center in ((90, 100), (250, 100)):
            cv2.rectangle(frame, (center[0] - 30, center[1] - 30), (center[0] + 30, center[1] + 30), (220, 220, 220), -1)
        for center in ((410, 100), (510, 210)):
            cv2.circle(frame, center, 30, (220, 220, 220), -1)
        result, _, _ = detector().detect(
            frame, frame_index=0, timestamp_s=0.0, timestamp_kind="video_media_timeline"
        )
        self.assertEqual(len(result.detections), 4)
        self.assertEqual([item.class_name for item in result.detections], ["cube", "cube", "cylinder", "cylinder"])

    def test_roi_uses_original_image_coordinates(self) -> None:
        frame = np.full((300, 500, 3), 30, dtype=np.uint8)
        cv2.circle(frame, (350, 150), 35, (220, 220, 220), -1)
        cv2.circle(frame, (40, 40), 25, (220, 220, 220), -1)
        result, _, _ = detector(roi=(200, 50, 480, 260)).detect(
            frame, frame_index=0, timestamp_s=None, timestamp_kind="still_no_media_time"
        )
        self.assertEqual(len(result.detections), 1)
        self.assertAlmostEqual(result.detections[0].center_px[0], 350, delta=1)
        self.assertAlmostEqual(result.detections[0].center_px[1], 150, delta=1)

    def test_empty_and_ambiguous_frames_export_no_detection(self) -> None:
        empty = np.full((200, 300, 3), 30, dtype=np.uint8)
        result, _, _ = detector().detect(
            empty, frame_index=0, timestamp_s=None, timestamp_kind="still_no_media_time"
        )
        self.assertEqual(result.detections, ())

        cv2.ellipse(empty, (150, 100), (70, 22), 0, 0, 360, (220, 220, 220), -1)
        result, _, diagnostics = detector().detect(
            empty, frame_index=1, timestamp_s=None, timestamp_kind="still_no_media_time"
        )
        self.assertEqual(result.detections, ())
        self.assertIn("not_near_square_or_circle", {item.rejection_reason for item in diagnostics})

    def test_no_workspace_coordinates_are_exported(self) -> None:
        result, _, _ = detector().detect(
            controlled_frame(), frame_index=0, timestamp_s=0.0, timestamp_kind="video_media_timeline"
        )
        payload = result.to_dict()
        self.assertNotIn("x_mm", str(payload))
        self.assertNotIn("workspace", str(payload))


class UnifiedInterfaceTest(unittest.TestCase):
    def test_yolo_record_adapter_preserves_multiple_detections(self) -> None:
        raw = {
            "frame_index": 12,
            "timestamp_s": 0.4,
            "timestamp_kind": "video_media_timeline",
            "image_width_px": 640,
            "image_height_px": 480,
            "detections": [
                {"class_id": 1, "class_name": "cylinder", "confidence": 0.8, "bbox_xyxy": [300, 100, 360, 180]},
                {"class_id": 0, "class_name": "cube", "confidence": 0.9, "bbox_xyxy": [100, 100, 160, 160]},
            ],
        }
        result = adapt_yolo_record(raw)
        self.assertEqual([item.class_name for item in result.detections], ["cube", "cylinder"])
        self.assertEqual(result.detections[0].center_px, (130.0, 130.0))
        self.assertTrue(all(item.valid for item in result.detections))

    def test_no_yolo_detection_is_an_empty_list_not_a_stale_target(self) -> None:
        raw = {
            "frame_index": 13,
            "timestamp_s": 0.5,
            "timestamp_kind": "video_media_timeline",
            "image_width_px": 640,
            "image_height_px": 480,
            "detections": [],
        }
        self.assertEqual(adapt_yolo_record(raw).detections, ())

    def test_interface_rejects_mismatched_class_name(self) -> None:
        with self.assertRaises(ValueError):
            ObjectDetection(0, "cylinder", 0.9, (0, 0, 20, 20), (10, 10), 0.0, True)


if __name__ == "__main__":
    unittest.main()
