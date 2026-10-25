"""PS 数据转换仅检查 JSON 结构，不访问通信设备。"""
import json
import unittest

from integration import to_ps_payload
from vision.results import Detection, FrameResult


class PayloadTests(unittest.TestCase):
    def test_multiple_targets(self):
        items = (Detection.from_bbox(0, .8, (1, 2, 11, 12), 640, 480),
                 Detection.from_bbox(1, .9, (20, 30, 40, 50), 640, 480))
        payload = to_ps_payload(FrameResult(640, 480, items))
        self.assertEqual([x["class_id"] for x in payload["detections"]], [0, 1])
        self.assertEqual(payload["detections"][1]["center_x"], 30)
        json.dumps(payload)

    def test_no_target(self):
        self.assertEqual(to_ps_payload(FrameResult(640, 480, ()))['detections'], [])
