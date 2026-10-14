"""Fixed-camera scene locking, still capture, and baseline comparison."""
# SPDX-License-Identifier: AGPL-3.0-only
# 职责：把"相机与场景"变成可复现的固定工况——枚举相机、尝试锁定曝光/白平衡/增益、
#       拍摄纯背景与含工件实拍图，并把每次开机的画面与基线比对。
# 本模块不做相机内参/畸变标定，也不产生任何毫米坐标；只负责工况锁定与证据留存。
#
# 为什么需要它：Windows 上没有 v4l2-ctl，而 G4 的"场景锁定"必须可记录、可复现。
# UVC 相机的曝光/白平衡是否真的能被锁定由驱动决定，因此本工具**如实打印读回值**：
# 读回值才是证据，写成功不代表锁住了。

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path

import cv2
import numpy as np

PROBE_MAX_INDEX = 4
DEFAULT_WARMUP = 10
DEFAULT_PIXEL_THRESHOLD = 12.0

BACKENDS = {
    "auto": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
}

CONTROL_PROPERTIES = {
    "width": cv2.CAP_PROP_FRAME_WIDTH,
    "height": cv2.CAP_PROP_FRAME_HEIGHT,
    "fps": cv2.CAP_PROP_FPS,
    "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
    "exposure": cv2.CAP_PROP_EXPOSURE,
    "gain": cv2.CAP_PROP_GAIN,
    "auto_wb": cv2.CAP_PROP_AUTO_WB,
    "wb_temperature": cv2.CAP_PROP_WB_TEMPERATURE,
    "brightness": cv2.CAP_PROP_BRIGHTNESS,
    "contrast": cv2.CAP_PROP_CONTRAST,
    "saturation": cv2.CAP_PROP_SATURATION,
    "buffer_size": cv2.CAP_PROP_BUFFERSIZE,
}

STATUS_APPLIED = "applied"
STATUS_NOT_APPLIED = "not_applied"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ControlReport:
    """一次性曝光/增益设置的"请求值 vs 读回值"记录。"""

    name: str
    requested: float
    readback: float | None
    status: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "requested": self.requested,
            "readback": None if self.readback is None else float(self.readback),
            "status": self.status,
        }


def parse_setting(text: str) -> tuple[str, float]:
    """解析 ``name=value``；名字必须是已知控制项，否则明确报错。"""
    if "=" not in text:
        raise argparse.ArgumentTypeError("设置必须是 name=value 形式")
    name, _, raw_value = text.partition("=")
    name = name.strip()
    if name not in CONTROL_PROPERTIES:
        known = ", ".join(sorted(CONTROL_PROPERTIES))
        raise argparse.ArgumentTypeError(f"未知控制项 {name!r}；可用: {known}")
    try:
        return name, float(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"value 必须是数字: {raw_value!r}") from exc


def classify_control(requested: float, readback: float | None, tolerance: float = 1e-6) -> str:
    """判定一次设置是否生效；读回无效一律记 unknown，不假装成功。"""
    if readback is None or not np.isfinite(readback):
        return STATUS_UNKNOWN
    return STATUS_APPLIED if abs(float(readback) - requested) <= tolerance else STATUS_NOT_APPLIED


def apply_controls(
    capture, settings: dict[str, float], *, tolerance: float = 1e-6
) -> list[ControlReport]:
    """逐项写入并立刻读回；返回每一项的请求/读回/状态。"""
    reports: list[ControlReport] = []
    for name, value in settings.items():
        prop = CONTROL_PROPERTIES[name]
        capture.set(prop, value)
        readback = capture.get(prop)
        readback_value = None if readback is None else float(readback)
        reports.append(
            ControlReport(
                name=name,
                requested=float(value),
                readback=readback_value,
                status=classify_control(float(value), readback_value, tolerance),
            )
        )
    return reports


def compare_frames(
    baseline_bgr: np.ndarray, frame_bgr: np.ndarray, *, pixel_threshold: float = DEFAULT_PIXEL_THRESHOLD
) -> dict:
    """把一张新画面与基线比：返回逐像素差异统计。

    用法是"每次开机先拍一张与纯背景图比一次"。``changed_pixel_ratio`` 超过多少算异常
    由团队按抓取容差批准，本函数只给数字，不预设结论。
    """
    baseline = np.asarray(baseline_bgr)
    frame = np.asarray(frame_bgr)
    if baseline.shape != frame.shape:
        return {
            "resolution_match": False,
            "baseline_shape": list(baseline.shape),
            "frame_shape": list(frame.shape),
            "mean_abs_diff": None,
            "max_abs_diff": None,
            "changed_pixel_ratio": None,
            "pixel_threshold": float(pixel_threshold),
        }
    difference = np.abs(frame.astype(np.float32) - baseline.astype(np.float32))
    per_pixel = difference.max(axis=2) if difference.ndim == 3 else difference
    return {
        "resolution_match": True,
        "baseline_shape": list(baseline.shape),
        "frame_shape": list(frame.shape),
        "mean_abs_diff": float(difference.mean()),
        "max_abs_diff": float(difference.max()),
        "changed_pixel_ratio": float((per_pixel > pixel_threshold).mean()),
        "pixel_threshold": float(pixel_threshold),
    }


def read_image(path: Path) -> np.ndarray:
    """读取支持 Unicode 路径的图片。"""
    encoded = np.fromfile(Path(path), dtype=np.uint8)
    frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cannot decode image: {path}")
    return frame


def write_image(path: Path, image: np.ndarray) -> None:
    """写出 BGR 图片；编码失败时抛错，不留下半截文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise ValueError(f"cannot encode image: {path}")
    path.write_bytes(encoded.tobytes())


def open_capture(index: int, backend: str):
    """按指定后端打开相机；打不开返回 ``None``，不抛异常。"""
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {sorted(BACKENDS)}")
    capture = cv2.VideoCapture(index, BACKENDS[backend])
    if not capture.isOpened():
        capture.release()
        return None
    return capture


def probe_cameras(*, backend: str = "auto", max_index: int = PROBE_MAX_INDEX) -> list[dict]:
    """枚举可用相机索引并报告分辨率/帧率/后端；这是确定 ``--camera-index`` 的办法。"""
    results: list[dict] = []
    for index in range(max_index):
        capture = open_capture(index, backend)
        if capture is None:
            results.append({"index": index, "opened": False})
            continue
        results.append(
            {
                "index": index,
                "opened": True,
                "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": float(capture.get(cv2.CAP_PROP_FPS)),
                "backend": capture.getBackendName(),
            }
        )
        capture.release()
    return results


def grab_frames(capture, count: int, *, warmup: int = DEFAULT_WARMUP) -> list[np.ndarray]:
    """丢弃前 ``warmup`` 帧后取 ``count`` 帧；第一帧常是未曝光的废帧。"""
    for _ in range(max(warmup, 0)):
        capture.read()
    frames: list[np.ndarray] = []
    for _ in range(count):
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    return frames


def _build_parser() -> argparse.ArgumentParser:
    """构造 CLI；``--probe`` 与采集互斥使用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="枚举相机索引后退出")
    parser.add_argument("--camera-index", type=int, default=1)
    parser.add_argument("--backend", choices=sorted(BACKENDS), default="auto")
    parser.add_argument("--set", dest="settings", type=parse_setting, action="append", default=[])
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--snapshot", type=Path, help="采集目录；留空则只做--compare")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--prefix", default="frame")
    parser.add_argument("--compare", type=Path, help="基线图片；与本次首帧比对")
    parser.add_argument("--pixel-threshold", type=float, default=DEFAULT_PIXEL_THRESHOLD)
    parser.add_argument("--json", action="store_true", help="只输出 JSON，便于存档")
    return parser


def main(argv=None) -> int:
    """执行枚举 / 锁定 / 采集 / 比对，并打印可归档的记录。"""
    args = _build_parser().parse_args(argv)
    settings = dict(args.settings)

    if args.probe:
        payload = {"probe": probe_cameras(backend=args.backend)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    capture = open_capture(args.camera_index, args.backend)
    if capture is None:
        print(f"无法打开相机 index={args.camera_index} backend={args.backend}")
        return 1

    record: dict = {
        "requested_index": args.camera_index,
        "backend": args.backend,
        "controls": [],
        "snapshots": [],
    }
    try:
        record["controls"] = [item.to_dict() for item in apply_controls(capture, settings)]
        record["effective"] = {
            "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(capture.get(cv2.CAP_PROP_FPS)),
        }
        frames = grab_frames(capture, args.count, warmup=args.warmup)
        if not frames:
            print("相机未返回任何帧")
            return 1
        if args.snapshot is not None:
            for offset, frame in enumerate(frames):
                target = args.snapshot / f"{args.prefix}_{offset:03d}.png"
                write_image(target, frame)
                record["snapshots"].append(str(target))
        if args.compare is not None:
            record["compare"] = compare_frames(
                read_image(args.compare), frames[0], pixel_threshold=args.pixel_threshold
            )
    finally:
        capture.release()

    if args.json:
        print(json.dumps(record, ensure_ascii=False))
    else:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        for item in record["controls"]:
            if item["status"] != STATUS_APPLIED:
                print(
                    f"[warn] {item['name']}: 请求 {item['requested']} 读回 {item['readback']} "
                    f"-> {item['status']}（没有真正锁住，需换后端或改相机设置）"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
