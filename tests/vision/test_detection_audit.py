"""``src.vision.detection_audit`` 的离线单元测试。

这些测试只使用合成记录，不访问相机、不加载 YOLO 权重、不驱动机械臂。
它们验证的是"逐帧数量一致性"的判定与统计口径，不代表任何现场识别准确率。
"""
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.vision.detection_audit import (
    KIND_FEWER,
    KIND_MORE,
    RECALL_PRECISION_STATE,
    DetectedObject,
    FrameDetections,
    build_parser,
    export_suspect_frames,
    load_frames,
    main,
    parse_record,
    render_text,
    resolve_records_path,
    summarize,
)

import cv2
import numpy as np


def frame(index: int, *objects: tuple[str, float]) -> FrameDetections:
    """构造一帧合成检测；不传目标即零检出帧。"""
    return FrameDetections(index, tuple(DetectedObject(name, conf) for name, conf in objects))


class SummarizeTests(unittest.TestCase):
    """逐帧数量一致性的判定与统计口径。"""

    def test_all_frames_conforming(self) -> None:
        frames = tuple(frame(i, ("cube", 0.9), ("cube", 0.8)) for i in range(5))
        summary = summarize(frames, expect_count=2, conf_min=0.5)
        self.assertEqual(summary["frames"], 5)
        self.assertEqual(summary["frames_conforming"], 5)
        self.assertEqual(summary["conforming_ratio"], 1.0)
        self.assertEqual(summary["frames_fewer"], 0)
        self.assertEqual(summary["frames_more"], 0)
        self.assertEqual(summary["longest_conforming_run"], 5)
        self.assertIsNone(summary["first_nonconforming_frame_index"])
        self.assertEqual(summary["suspect_frames"], [])

    def test_fewer_than_expected_is_flagged_with_frame_index(self) -> None:
        frames = (frame(10, ("cube", 0.9)), frame(11), frame(12, ("cube", 0.9)))
        summary = summarize(frames, expect_count=1, conf_min=0.5)
        self.assertEqual(summary["frames_fewer"], 1)
        self.assertEqual(summary["suspect_frames"][0]["frame_index"], 11)
        self.assertEqual(summary["suspect_frames"][0]["kind"], KIND_FEWER)
        self.assertEqual(summary["suspect_frames"][0]["total"], 0)
        self.assertEqual(summary["first_nonconforming_frame_index"], 11)

    def test_more_than_expected_is_flagged(self) -> None:
        frames = (frame(0, ("cube", 0.9), ("cube", 0.7), ("cylinder", 0.6)),)
        summary = summarize(frames, expect_count=2, conf_min=0.5)
        self.assertEqual(summary["frames_more"], 1)
        self.assertEqual(summary["frames_fewer"], 0)
        self.assertEqual(summary["suspect_frames"][0]["kind"], KIND_MORE)
        self.assertEqual(summary["suspect_frames"][0]["class_counts"], {"cube": 2, "cylinder": 1})

    def test_class_totals_and_confidence_statistics(self) -> None:
        frames = (
            frame(0, ("cube", 0.4), ("cylinder", 0.8)),
            frame(1, ("cube", 0.6), ("cylinder", 1.0)),
        )
        summary = summarize(frames, expect_count=2, conf_min=0.5)
        self.assertEqual(summary["detections_total"], 4)
        self.assertEqual(summary["detections_by_class"], {"cube": 2, "cylinder": 2})
        self.assertAlmostEqual(summary["confidence_by_class"]["cube"]["min"], 0.4)
        self.assertAlmostEqual(summary["confidence_by_class"]["cube"]["mean"], 0.5)
        self.assertAlmostEqual(summary["confidence_by_class"]["cube"]["p50"], 0.5)
        self.assertAlmostEqual(summary["confidence_by_class"]["cylinder"]["min"], 0.8)

    def test_below_conf_min_counted_separately(self) -> None:
        frames = (frame(0, ("cube", 0.49), ("cylinder", 0.5)),)
        summary = summarize(frames, expect_count=2, conf_min=0.5)
        self.assertEqual(summary["detections_below_conf_min"], 1)
        self.assertEqual(summary["frames_conforming"], 1)  # 数量对即合规，低置信度只另行计数

    def test_longest_run_and_first_nonconforming_across_gaps(self) -> None:
        frames = (
            frame(0, ("cube", 0.9)),
            frame(1),
            frame(2, ("cube", 0.9)),
            frame(3, ("cube", 0.9)),
            frame(4, ("cube", 0.9)),
            frame(5, ("cube", 0.9)),
            frame(6),
        )
        summary = summarize(frames, expect_count=1, conf_min=0.5)
        self.assertEqual(summary["frames_conforming"], 5)
        self.assertEqual(summary["longest_conforming_run"], 4)
        self.assertEqual(summary["first_nonconforming_frame_index"], 1)
        self.assertEqual([s["frame_index"] for s in summary["suspect_frames"]], [1, 6])

    def test_zero_expectation_requires_empty_frames(self) -> None:
        summary = summarize((frame(0), frame(1, ("cube", 0.9))), expect_count=0, conf_min=0.5)
        self.assertEqual(summary["frames_conforming"], 1)
        self.assertEqual(summary["frames_more"], 1)

    def test_recall_precision_is_explicitly_not_claimed(self) -> None:
        summary = summarize((frame(0, ("cube", 0.9)),), expect_count=1, conf_min=0.5)
        self.assertEqual(summary["recall_precision"], RECALL_PRECISION_STATE)

    def test_invalid_arguments_rejected(self) -> None:
        frames = (frame(0, ("cube", 0.9)),)
        with self.assertRaises(ValueError):
            summarize(frames, expect_count=-1, conf_min=0.5)
        with self.assertRaises(ValueError):
            summarize(frames, expect_count=1, conf_min=1.5)
        with self.assertRaises(ValueError):
            summarize((), expect_count=1, conf_min=0.5)


class RecordParsingTests(unittest.TestCase):
    """两种已知 JSONL 结构与路径解析。"""

    def test_parse_flat_record(self) -> None:
        parsed = parse_record({
            "frame_index": 3,
            "detections": [{"class_name": "cube", "confidence": 0.75}],
        })
        self.assertEqual(parsed.frame_index, 3)
        self.assertEqual(parsed.total, 1)
        self.assertEqual(parsed.objects[0].class_name, "cube")

    def test_parse_nested_record_uses_yolo_a(self) -> None:
        parsed = parse_record({
            "frame_index": 7,
            "algorithms": {"yolo_a": {"detections": []}, "opencv": {"detections": [1, 2, 3]}},
        })
        self.assertEqual(parsed.frame_index, 7)
        self.assertEqual(parsed.total, 0)  # 只用 yolo_a，不把 opencv 结果算进来

    def test_parse_nested_record_without_yolo_a_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_record({"frame_index": 0, "algorithms": {"opencv": {"detections": []}}})

    def test_parse_record_requires_frame_index_and_confidences(self) -> None:
        with self.assertRaises(ValueError):
            parse_record({"detections": []})
        with self.assertRaises(ValueError):
            parse_record({"frame_index": 0, "detections": [{"class_name": "cube"}]})

    def test_load_frames_and_resolve_records_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw) / "run"
            run_dir.mkdir()
            records = run_dir / "detections.jsonl"
            records.write_text(
                json.dumps({"frame_index": 0, "detections": []}) + "\n"
                + "\n"
                + json.dumps({"frame_index": 1, "detections": [
                    {"class_name": "cube", "confidence": 0.9}]}) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(resolve_records_path(run_dir), records)
            self.assertEqual(resolve_records_path(records), records)
            frames = load_frames(records)
            self.assertEqual([f.frame_index for f in frames], [0, 1])
            self.assertEqual(frames[1].total, 1)

    def test_resolve_rejects_directory_without_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ValueError):
                resolve_records_path(Path(raw))

    def test_load_frames_rejects_empty_and_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            empty = Path(raw) / "empty.jsonl"
            empty.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_frames(empty)
            broken = Path(raw) / "broken.jsonl"
            broken.write_text("{not json}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_frames(broken)


class RenderTests(unittest.TestCase):
    """人类可读报告的要点必须出现。"""

    def test_render_reports_counts_and_suspects(self) -> None:
        summary = summarize((frame(0, ("cube", 0.9)), frame(1)), expect_count=1, conf_min=0.5)
        text = render_text(summary)
        self.assertIn("受审帧数        2", text)
        self.assertIn("少检嫌疑        1", text)
        self.assertIn("frame=     1", text)
        self.assertIn("recall/precision 未计算", text)

    def test_render_marks_absent_suspects(self) -> None:
        summary = summarize((frame(0, ("cube", 0.9)),), expect_count=1, conf_min=0.5)
        self.assertIn("可疑帧：无", render_text(summary))


class CliTests(unittest.TestCase):
    """CLI 契约：--expect 必填、输出目录不可覆盖、成功时写两份报告。"""

    def test_expect_is_required(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["records.jsonl", "--output", "out"])

    def test_main_refuses_existing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw) / "run"
            run_dir.mkdir()
            (run_dir / "detections.jsonl").write_text(
                json.dumps({"frame_index": 0, "detections": []}) + "\n", encoding="utf-8")
            out = Path(raw) / "out"
            out.mkdir()
            with self.assertRaises(FileExistsError):
                main([str(run_dir), "--expect", "1", "--output", str(out)])

    def test_main_writes_audit_reports(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw) / "run"
            run_dir.mkdir()
            (run_dir / "detections.jsonl").write_text(
                json.dumps({"frame_index": 0, "detections": [
                    {"class_name": "cube", "confidence": 0.9}]}) + "\n", encoding="utf-8")
            out = Path(raw) / "out"
            main([str(run_dir), "--expect", "1", "--conf-min", "0.5", "--output", str(out)])
            summary = json.loads((out / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["frames_conforming"], 1)
            self.assertEqual(summary["exported_suspect_frames"], [])
            self.assertIn("受审帧数", (out / "audit.txt").read_text(encoding="utf-8"))

    def test_max_export_must_not_be_negative(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            run_dir = Path(raw) / "run"
            run_dir.mkdir()
            (run_dir / "detections.jsonl").write_text(
                json.dumps({"frame_index": 0, "detections": []}) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                main([str(run_dir), "--expect", "1", "--max-export", "-1",
                      "--output", str(Path(raw) / "out")])


class ExportTests(unittest.TestCase):
    """抽帧层：从图片目录或视频取出可疑帧；帧号越界必须明确报错。"""

    @staticmethod
    def _write_png(path: Path, value: int) -> None:
        ok, encoded = cv2.imencode(".png", np.full((8, 8, 3), value, dtype=np.uint8))
        if not ok:
            raise AssertionError(f"无法编码测试图片: {path}")
        encoded.tofile(path)

    def test_export_from_image_directory_sorted_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "images"
            source.mkdir()
            for index in range(3):
                self._write_png(source / f"{index:06d}.png", index * 40)
            output = Path(raw) / "out"
            written = export_suspect_frames(source, [2, 0], output, limit=5)
            self.assertEqual(written, [0, 2])  # 按帧号升序
            for index in (0, 2):
                self.assertTrue((output / f"suspect_{index:06d}.png").is_file())

    def test_export_respects_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "images"
            source.mkdir()
            for index in range(3):
                self._write_png(source / f"{index:06d}.png", index)
            written = export_suspect_frames(source, [0, 1, 2], Path(raw) / "out", limit=2)
            self.assertEqual(written, [0, 1])

    def test_export_rejects_out_of_range_image_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "images"
            source.mkdir()
            self._write_png(source / "000000.png", 0)
            with self.assertRaises(ValueError):
                export_suspect_frames(source, [1], Path(raw) / "out", limit=5)

    def test_export_from_video(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            video = Path(raw) / "clip.mp4"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (16, 16))
            if not writer.isOpened():
                self.skipTest("本机 OpenCV 无法创建 mp4v 视频，跳过视频抽帧用例")
            try:
                for index in range(5):
                    writer.write(np.full((16, 16, 3), index * 30, dtype=np.uint8))
            finally:
                writer.release()
            output = Path(raw) / "out"
            written = export_suspect_frames(video, [3, 1], output, limit=10)
            self.assertEqual(written, [1, 3])
            for index in (1, 3):
                self.assertTrue((output / f"suspect_{index:06d}.png").is_file())


if __name__ == "__main__":
    unittest.main()
