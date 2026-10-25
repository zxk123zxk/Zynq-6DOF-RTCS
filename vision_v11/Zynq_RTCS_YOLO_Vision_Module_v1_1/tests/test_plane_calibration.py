"""平面标定换算与保存，不访问摄像头。"""
import json
import tempfile
import unittest
from pathlib import Path

from integration import to_ps_payload
from vision.plane_calibration import PlaneCalibration
from vision.results import Detection, FrameResult


CORNERS = ((100, 50), (500, 60), (520, 360), (90, 350))


class PlaneCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.calib = PlaneCalibration.from_corners(CORNERS, (200, 150), (640, 480))

    def test_corners_map_to_board(self):
        for px, mm in zip(CORNERS, ((0, 0), (200, 0), (200, 150), (0, 150))):
            for a, b in zip(self.calib.to_mm(*px), mm):
                self.assertAlmostEqual(a, b, places=4)

    def test_round_trip(self):
        x, y = self.calib.to_px(*self.calib.to_mm(300, 200))
        self.assertAlmostEqual(x, 300, places=4)
        self.assertAlmostEqual(y, 200, places=4)

    def test_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            self.calib.save(path)
            self.assertEqual(PlaneCalibration.load(path), self.calib)
            json.loads(path.read_text(encoding="utf-8"))

    def test_rejects_bad_order(self):
        with self.assertRaises(ValueError):
            PlaneCalibration.from_corners((CORNERS[0], CORNERS[2], CORNERS[1], CORNERS[3]),
                                          (200, 150), (640, 480))

    def test_payload_mm(self):
        item = Detection.from_bbox(0, .9, (90, 40, 110, 60), 640, 480)
        det = to_ps_payload(FrameResult(640, 480, (item,)), self.calib)["detections"][0]
        self.assertAlmostEqual(det["center_x_mm"], 0, places=4)
        self.assertAlmostEqual(det["center_y_mm"], 0, places=4)
        self.assertNotIn("center_x_mm", to_ps_payload(FrameResult(640, 480, (item,)))["detections"][0])
