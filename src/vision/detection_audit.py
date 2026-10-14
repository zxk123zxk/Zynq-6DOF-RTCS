"""固定背景下的检出点检：按已知目标数判定逐帧数量一致性，并导出可疑帧。

用途：把一次运行的 ``detections.jsonl`` 变成"哪些帧的检出数量与现场实际放置数量不符"
的清单，交给人工在导出的帧上裁定是真漏检还是真误检。

边界：本模块**不输出 recall/precision**——那需要人工逐帧真值，程序不替人下结论；
也不输出任何毫米坐标。它只读记录、只写点检报告与可疑帧，不驱动机械臂。
"""
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import median

import cv2
import numpy as np

RECORDS_NAME = "detections.jsonl"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
KIND_FEWER = "fewer_than_expected"
KIND_MORE = "more_than_expected"
RECALL_PRECISION_STATE = "not_computed_requires_manual_adjudication_on_suspect_frames"


@dataclass(frozen=True)
class DetectedObject:
    """一条检测：只保留审计用得到的类别名与置信度。"""

    class_name: str
    confidence: float


@dataclass(frozen=True)
class FrameDetections:
    """一帧的检测集合；空元组表示该帧零检出，绝不沿用上一帧。"""

    frame_index: int
    objects: tuple[DetectedObject, ...]

    @property
    def total(self) -> int:
        """该帧检出总数。"""
        return len(self.objects)

    def class_counts(self) -> dict[str, int]:
        """按类别统计该帧检出数量。"""
        counts: dict[str, int] = {}
        for obj in self.objects:
            counts[obj.class_name] = counts.get(obj.class_name, 0) + 1
        return counts


def resolve_records_path(target: Path) -> Path:
    """接受运行目录或直接指向 ``detections.jsonl``；其它路径明确拒绝。"""
    if target.is_dir():
        candidate = target / RECORDS_NAME
        if not candidate.is_file():
            raise ValueError(f"目录中没有 {RECORDS_NAME}: {target}")
        return candidate
    if target.is_file() and target.suffix.lower() == ".jsonl":
        return target
    raise ValueError(f"需要 {RECORDS_NAME} 或包含它的运行目录: {target}")


def parse_record(record: dict) -> FrameDetections:
    """解析一帧记录，兼容两种已知 JSONL 结构。

    扁平结构（``src.vision.yolo_inference``）用顶层 ``detections``；
    嵌套结构（``src.vision.cube_cylinder_live_test``）用 ``algorithms.yolo_a.detections``。
    两者都缺 ``detections`` 时视为该帧零检出，而不是数据缺失。
    """
    if "algorithms" in record:
        algorithms = record["algorithms"]
        if not isinstance(algorithms, dict) or "yolo_a" not in algorithms:
            raise ValueError("嵌套记录缺少 algorithms.yolo_a")
        payload = algorithms["yolo_a"]
    else:
        payload = record
    raw = payload.get("detections", [])
    if not isinstance(raw, list):
        raise ValueError("detections 必须是列表")
    objects = []
    for item in raw:
        name = item.get("class_name")
        confidence = item.get("confidence")
        if not isinstance(name, str) or not name:
            raise ValueError("检测记录缺少 class_name")
        if not isinstance(confidence, (int, float)):
            raise ValueError("检测记录缺少 confidence")
        objects.append(DetectedObject(name, float(confidence)))
    if "frame_index" not in record:
        raise ValueError("记录缺少 frame_index")
    return FrameDetections(int(record["frame_index"]), tuple(objects))


def load_frames(path: Path) -> tuple[FrameDetections, ...]:
    """读取 JSONL 的全部逐帧记录，保持文件顺序；空文件明确拒绝。"""
    frames = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"第 {line_number} 行不是合法 JSON: {error}") from error
            frames.append(parse_record(record))
    if not frames:
        raise ValueError(f"没有可审计的帧记录: {path}")
    return tuple(frames)


def _confidence_stats(values: list[float]) -> dict[str, float]:
    """给出一类的 min/mean/p50；数值本身不代表跨场景真实准确率。"""
    return {
        "min": min(values),
        "mean": sum(values) / len(values),
        "p50": median(values),
    }


def summarize(frames: tuple[FrameDetections, ...], *, expect_count: int,
              conf_min: float) -> dict:
    """按"现场实际放置数量"判定逐帧是否合规，返回可直接序列化的摘要。

    ``expect_count`` 是现场真实放置的目标数（人工确认），不是模型输出。
    帧内数量等于它记为合规；少于它记为 ``fewer_than_expected``（漏检嫌疑），
    多于它记为 ``more_than_expected``（误检嫌疑）。二者都只是**嫌疑**，
    必须由人工在导出帧上裁定，因此摘要不给出 recall/precision。
    """
    if expect_count < 0:
        raise ValueError("expect_count 不能为负")
    if not 0.0 <= conf_min <= 1.0:
        raise ValueError("conf_min 必须在 [0, 1]")
    if not frames:
        raise ValueError("没有帧可审计")

    class_totals: dict[str, int] = {}
    confidences: dict[str, list[float]] = {}
    below_conf_min = 0
    suspects: list[dict] = []
    conforming = 0
    longest_run = 0
    current_run = 0
    first_nonconforming: int | None = None

    for frame in frames:
        for obj in frame.objects:
            class_totals[obj.class_name] = class_totals.get(obj.class_name, 0) + 1
            confidences.setdefault(obj.class_name, []).append(obj.confidence)
            if obj.confidence < conf_min:
                below_conf_min += 1
        if frame.total == expect_count:
            conforming += 1
            current_run += 1
            longest_run = max(longest_run, current_run)
            continue
        current_run = 0
        if first_nonconforming is None:
            first_nonconforming = frame.frame_index
        suspects.append({
            "frame_index": frame.frame_index,
            "total": frame.total,
            "class_counts": frame.class_counts(),
            "kind": KIND_FEWER if frame.total < expect_count else KIND_MORE,
        })

    frame_count = len(frames)
    return {
        "expect_count": expect_count,
        "conf_min": conf_min,
        "frames": frame_count,
        "frames_conforming": conforming,
        "conforming_ratio": conforming / frame_count,
        "frames_fewer": sum(1 for s in suspects if s["kind"] == KIND_FEWER),
        "frames_more": sum(1 for s in suspects if s["kind"] == KIND_MORE),
        "longest_conforming_run": longest_run,
        "first_nonconforming_frame_index": first_nonconforming,
        "detections_total": sum(class_totals.values()),
        "detections_by_class": class_totals,
        "confidence_by_class": {name: _confidence_stats(values)
                                for name, values in sorted(confidences.items())},
        "detections_below_conf_min": below_conf_min,
        "recall_precision": RECALL_PRECISION_STATE,
        "suspect_frames": suspects,
    }


def render_text(summary: dict, *, head: int = 20) -> str:
    """把摘要渲染成人类可读报告；可疑帧只列前 ``head`` 条，完整清单在 JSON 里。"""
    lines = [
        "RTCS 固定背景检出点检",
        f"  受审帧数        {summary['frames']}",
        f"  现场放置数量    {summary['expect_count']}",
        f"  合规帧          {summary['frames_conforming']} "
        f"({summary['conforming_ratio'] * 100:.1f}%)",
        f"  少检嫌疑        {summary['frames_fewer']}",
        f"  多检嫌疑        {summary['frames_more']}",
        f"  最长连续合规    {summary['longest_conforming_run']} 帧",
        f"  首个不合规帧号  {summary['first_nonconforming_frame_index']}",
        f"  检出总数        {summary['detections_total']} {summary['detections_by_class']}",
        f"  低于 conf_min   {summary['detections_below_conf_min']}（conf_min={summary['conf_min']}）",
    ]
    for name, stats in summary["confidence_by_class"].items():
        lines.append(f"  {name} 置信度      min={stats['min']:.3f} mean={stats['mean']:.3f} "
                     f"p50={stats['p50']:.3f}")
    lines.append(f"  recall/precision 未计算：{summary['recall_precision']}")
    suspects = summary["suspect_frames"]
    if suspects:
        lines.append(f"  可疑帧（前 {min(head, len(suspects))} / 共 {len(suspects)}）：")
        for item in suspects[:head]:
            lines.append(f"    frame={item['frame_index']:>6} kind={item['kind']:<22} "
                         f"total={item['total']} {item['class_counts']}")
    else:
        lines.append("  可疑帧：无")
    return "\n".join(lines) + "\n"


def _read_image(path: Path) -> np.ndarray:
    """读取支持非 ASCII 路径的图片并返回 BGR 数组。"""
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法解码图片: {path}")
    return image


def _write_image(path: Path, image: np.ndarray) -> None:
    """写出 PNG；编码失败明确报错，不静默跳过。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"无法编码图片: {path}")
    encoded.tofile(path)


def export_suspect_frames(source: Path, frame_indices: list[int], output_dir: Path,
                          *, limit: int) -> list[int]:
    """把可疑帧从原始视频或图片目录抽出为 PNG，供人工裁定。

    Camera 运行没有逐帧原图，可把 ``source`` 指向该 run 的 ``annotated.mp4``：
    抽出的帧已带框，便于判断"真漏检"还是"真误检"。只导出前 ``limit`` 个帧号，
    按帧号升序；来源无法打开或帧号超出范围时明确报错。
    """
    wanted = sorted(set(frame_indices))[:limit]
    if not wanted:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[int] = []

    if source.is_dir():
        images = sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        if not images:
            raise ValueError(f"图片目录为空: {source}")
        for index in wanted:
            if index >= len(images):
                raise ValueError(f"帧号 {index} 超出图片目录范围 ({len(images)} 张)")
            _write_image(output_dir / f"suspect_{index:06d}.png", _read_image(images[index]))
            written.append(index)
        return written

    if source.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError(f"不支持的抽帧来源: {source}")
    target = set(wanted)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise OSError(f"无法打开视频: {source}")
    try:
        index = 0
        while written != wanted:
            ok, frame = capture.read()
            if not ok:
                break
            if index in target:
                _write_image(output_dir / f"suspect_{index:06d}.png", frame)
                written.append(index)
            index += 1
    finally:
        capture.release()
    if written != wanted:
        raise ValueError(f"视频只有 {index} 帧，不足以取出帧号 {wanted}")
    return written


def build_parser() -> argparse.ArgumentParser:
    """创建命令行解析器；``--expect`` 必须由现场实际放置数量显式给出。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path,
                        help=f"{RECORDS_NAME} 路径，或包含它的运行目录")
    parser.add_argument("--expect", type=int, required=True,
                        help="现场实际放置的目标数量（人工确认，不是模型输出）")
    parser.add_argument("--conf-min", type=float, default=0.5,
                        help="低于此置信度另行计数为'勉强检出'；只是观察阈值，不是通过门槛")
    parser.add_argument("--frames-from", type=Path,
                        help="可选：原始视频或图片目录，用于抽出可疑帧")
    parser.add_argument("--max-export", type=int, default=30,
                        help="最多导出多少个可疑帧（默认 30）")
    parser.add_argument("--output", type=Path, required=True,
                        help="报告输出目录；必须不存在，以免覆盖历史证据")
    return parser


def main(argv=None) -> None:
    """运行点检：读记录 → 统计 → 可选抽帧 → 写报告；不访问相机、不驱动机械臂。"""
    args = build_parser().parse_args(argv)
    if args.output.exists():
        raise FileExistsError(f"拒绝覆盖已有输出目录: {args.output}")
    if args.max_export < 0:
        raise ValueError("--max-export 不能为负")
    records_path = resolve_records_path(args.records)
    frames = load_frames(records_path)
    summary = summarize(frames, expect_count=args.expect, conf_min=args.conf_min)

    # 先建目录并抽帧，再把最终字段补进摘要后写盘，避免报告漏掉实际导出的帧。
    args.output.mkdir(parents=True)
    exported: list[int] = []
    if args.frames_from is not None:
        exported = export_suspect_frames(
            args.frames_from, [s["frame_index"] for s in summary["suspect_frames"]],
            args.output / "suspect_frames", limit=args.max_export)

    summary["records_path"] = str(records_path.resolve())
    summary["frames_first_index"] = frames[0].frame_index
    summary["frames_last_index"] = frames[-1].frame_index
    summary["exported_suspect_frames"] = exported
    (args.output / "audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "audit.txt").write_text(render_text(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
