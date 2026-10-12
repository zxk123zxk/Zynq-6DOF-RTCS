"""Isolated YOLO11n inference for images, image directories, and local videos."""
# SPDX-License-Identifier: AGPL-3.0-only
# 职责：隔离加载冻结的 cube/cylinder YOLO 权重，并输出逐帧检测、像素位置和可视化。
# 本模块不做异常目标选择，也不输出未经真实标定的毫米坐标。

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Iterable

import cv2
import numpy as np
from ultralytics import YOLO


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
EXPECTED_NAMES = {0: "cube", 1: "cylinder"}
CLASS_ROLES = {0: "normal", 1: "anomaly"}


@dataclass(frozen=True)
class YoloDetection:
    """单个 YOLO 检测结果，bbox 和 center 均为当前输入图像的像素坐标。

    图像坐标系以左上角为原点，x/u 向右、y/v 向下。``confidence`` 是模型输出的
    置信度，并已受推理 ``conf`` 阈值过滤，不代表跨场景真实性保证。
    ``role`` 是早期接口遗留字段，当前正式流程只依据 class_id/class_name。
    """

    class_id: int
    class_name: str
    role: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]
    center_px: tuple[float, float]


@dataclass(frozen=True)
class YoloFrameResult:
    """一帧图像的零到多个有效 YOLO 检测及时间信息。

    ``timestamp_s`` 的语义由 ``timestamp_kind`` 指定；静态图片为 ``None``，本地
    视频使用媒体时间轴。``processing_monotonic_timestamp_s`` 和 latency 使用单调
    时钟，只适合性能计时，不是相机硬件曝光时间。
    """

    source: str
    frame_index: int
    timestamp_s: float | None
    timestamp_kind: str
    processing_monotonic_timestamp_s: float
    processing_latency_s: float
    image_width_px: int
    image_height_px: int
    detections: tuple[YoloDetection, ...]

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典，不改变字段单位或有效性语义。"""
        return asdict(self)


def _read_image(path: Path) -> np.ndarray:
    """读取支持 Unicode 路径的本地图片并返回 BGR 数组。"""
    encoded = np.fromfile(path, dtype=np.uint8)
    frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cannot decode image: {path}")
    return frame


def _write_image(path: Path, image: np.ndarray) -> None:
    """保存 BGR 可视化图；编码失败时抛出 ``ValueError``。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix, image)
    if not ok:
        raise ValueError(f"cannot encode image: {path}")
    path.write_bytes(encoded.tobytes())


def detections_from_result(result) -> tuple[YoloDetection, ...]:
    """把 Ultralytics 单帧结果转换为稳定的两类像素检测元组。

    模型若输出 0/1 以外类别会抛出 ``ValueError``；没有 boxes 时返回空元组，
    不生成无效坐标，也不复用上一帧结果。
    """
    detections = []
    if result.boxes is None:
        return ()
    xyxy = result.boxes.xyxy.detach().cpu().numpy()
    confidences = result.boxes.conf.detach().cpu().numpy()
    classes = result.boxes.cls.detach().cpu().numpy().astype(int)
    for box, confidence, raw_class_id in zip(xyxy, confidences, classes, strict=True):
        class_id = int(raw_class_id)
        if class_id not in EXPECTED_NAMES:
            raise ValueError(f"model emitted unexpected class_id={class_id}")
        x1, y1, x2, y2 = (float(value) for value in box)
        detections.append(
            YoloDetection(
                class_id=class_id,
                class_name=EXPECTED_NAMES[class_id],
                role=CLASS_ROLES[class_id],
                confidence=float(confidence),
                bbox_xyxy=(x1, y1, x2, y2),
                center_px=((x1 + x2) / 2.0, (y1 + y2) / 2.0),
            )
        )
    return tuple(detections)


class IsolatedYoloInference:
    """冻结 YOLO 权重的轻量推理封装。

    初始化时校验类别必须严格为 ``0=cube``、``1=cylinder``。``confidence`` 是
    Ultralytics 推理阈值，``imgsz`` 是模型输入尺寸；二者不应被解释为目标的
    物理尺寸或真实场景准确率保证。
    """

    def __init__(self, weights: Path, *, confidence: float, imgsz: int, device: str) -> None:
        """加载权重并校验阈值、输入尺寸与模型类别映射。"""
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if imgsz <= 0:
            raise ValueError("imgsz must be positive")
        self.model = YOLO(str(weights))
        names = {int(key): value for key, value in self.model.names.items()}
        if names != EXPECTED_NAMES:
            raise ValueError(f"unexpected model classes: {names}; expected {EXPECTED_NAMES}")
        self.confidence = confidence
        self.imgsz = imgsz
        self.device = device

    def infer_frame(
        self,
        frame_bgr: np.ndarray,
        *,
        source: str,
        frame_index: int,
        timestamp_s: float | None,
        timestamp_kind: str,
    ) -> tuple[YoloFrameResult, np.ndarray]:
        """推理一帧 BGR 图像，返回结构化记录和 Ultralytics 绘制图。

        bbox/center 相对于传入 ``frame_bgr``。若调用方先裁剪 ROI，调用方负责把
        局部像素坐标恢复到原图；本方法不会推断 ROI 偏移。
        """
        started = time.perf_counter()
        result = self.model.predict(
            source=frame_bgr,
            conf=self.confidence,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )[0]
        finished = time.perf_counter()
        height, width = frame_bgr.shape[:2]
        record = YoloFrameResult(
            source=source,
            frame_index=frame_index,
            timestamp_s=timestamp_s,
            timestamp_kind=timestamp_kind,
            processing_monotonic_timestamp_s=finished,
            processing_latency_s=finished - started,
            image_width_px=width,
            image_height_px=height,
            detections=detections_from_result(result),
        )
        return record, result.plot()


def _write_records(path: Path, records: Iterable[YoloFrameResult]) -> None:
    """将逐帧记录写为 JSON 或 JSONL；其他后缀会被明确拒绝。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    records = list(records)
    if path.suffix.lower() == ".jsonl":
        with path.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    elif path.suffix.lower() == ".json":
        path.write_text(
            json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        raise ValueError("--output-records must end in .json or .jsonl")


def _run_images(
    engine: IsolatedYoloInference,
    images: list[Path],
    *,
    output_visual: Path,
) -> list[YoloFrameResult]:
    """按文件名顺序处理静态图片；图片没有连续运动时间戳。"""
    output_visual.mkdir(parents=True, exist_ok=True)
    records = []
    for frame_index, image_path in enumerate(images):
        frame = _read_image(image_path)
        record, annotated = engine.infer_frame(
            frame,
            source=str(image_path.resolve()),
            frame_index=frame_index,
            timestamp_s=None,
            timestamp_kind="not_available_for_still_image",
        )
        _write_image(output_visual / image_path.name, annotated)
        records.append(record)
    return records


def _run_video(
    engine: IsolatedYoloInference,
    video_path: Path,
    *,
    output_visual: Path,
) -> list[YoloFrameResult]:
    """处理真实本地视频并使用 ``frame_index / FPS`` 作为媒体时间轴。

    视频无法打开、FPS/尺寸无效或输出视频无法创建时抛出异常；读取结束正常返回。
    """
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise OSError(f"cannot open video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not np.isfinite(fps) or fps <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise ValueError("video must provide valid FPS and dimensions")
    output_visual.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_visual), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        capture.release()
        raise OSError(f"cannot create output video: {output_visual}")

    records = []
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            record, annotated = engine.infer_frame(
                frame,
                source=str(video_path.resolve()),
                frame_index=frame_index,
                timestamp_s=frame_index / fps,
                timestamp_kind="video_media_timeline",
            )
            writer.write(annotated)
            records.append(record)
            frame_index += 1
    finally:
        capture.release()
        writer.release()
    return records


def main() -> None:
    """解析 CLI，选择图片、目录或视频路径并输出结构化结果与性能摘要。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="image, image directory, or local video")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output-visual", type=Path, required=True)
    parser.add_argument("--output-records", type=Path, required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(args.input)
    engine = IsolatedYoloInference(
        args.weights, confidence=args.conf, imgsz=args.imgsz, device=args.device
    )
    processing_started = time.perf_counter()

    if args.input.is_dir():
        images = sorted(
            path for path in args.input.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
        )
        if not images:
            raise ValueError(f"directory contains no supported images: {args.input}")
        records = _run_images(engine, images, output_visual=args.output_visual)
        input_kind = "image_directory"
    elif args.input.suffix.lower() in IMAGE_SUFFIXES:
        records = _run_images(engine, [args.input], output_visual=args.output_visual)
        input_kind = "single_image"
    elif args.input.suffix.lower() in VIDEO_SUFFIXES:
        records = _run_video(engine, args.input, output_visual=args.output_visual)
        input_kind = "local_video"
    else:
        raise ValueError(f"unsupported input: {args.input}")

    _write_records(args.output_records, records)
    end_to_end_wall_s = time.perf_counter() - processing_started
    elapsed = sum(record.processing_latency_s for record in records)
    print(
        json.dumps(
            {
                "status": "complete",
                "input_kind": input_kind,
                "frames": len(records),
                "detections": sum(len(record.detections) for record in records),
                "model_processing_s": elapsed,
                "model_processing_fps": len(records) / elapsed if elapsed > 0 else None,
                "end_to_end_wall_s": end_to_end_wall_s,
                "end_to_end_fps": len(records) / end_to_end_wall_s if end_to_end_wall_s > 0 else None,
                "confidence": args.conf,
                "imgsz": args.imgsz,
                "records": str(args.output_records.resolve()),
                "visual": str(args.output_visual.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
