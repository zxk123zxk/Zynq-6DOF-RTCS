"""临时诊断：统计新增绿带 run 的逐帧检出趋势，并抽出后半段俯拍画面。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "vision_runs" / "绿色传送带"
OUT = ROOT / "tmp" / "frames_belt"
OUT.mkdir(parents=True, exist_ok=True)


def load_records(path: Path) -> list[dict]:
    """读取 detections.jsonl，兼容两种嵌套结构。"""
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            algorithms = record.get("algorithms")
            if isinstance(algorithms, dict) and "yolo_a" in algorithms:
                detections = algorithms["yolo_a"].get("detections", [])
            else:
                detections = record.get("detections", [])
            rows.append(
                {
                    "frame_index": int(record["frame_index"]),
                    "count": len(detections),
                    "classes": Counter(item["class_name"] for item in detections),
                    "max_conf": max((float(item["confidence"]) for item in detections), default=0.0),
                }
            )
    return rows


rows = load_records(RUN / "detections.jsonl")
print(f"frames={len(rows)}  first={rows[0]['frame_index']}  last={rows[-1]['frame_index']}")

print("\n每 100 帧：平均检出数 / 检出数分布 / 最高置信度均值 / 类别统计")
for start in range(0, len(rows), 100):
    bucket = rows[start:start + 100]
    counts = [row["count"] for row in bucket]
    distribution = Counter(counts)
    classes = Counter()
    for row in bucket:
        classes.update(row["classes"])
    confidences = [row["max_conf"] for row in bucket]
    top = ", ".join(f"{k}个:{v}帧" for k, v in sorted(distribution.items()))
    print(
        f"  {start:>4}-{start + len(bucket) - 1:>4}  mean={sum(counts) / len(counts):5.2f}  "
        f"mean_maxconf={sum(confidences) / len(confidences):.3f}  {dict(classes)}  [{top}]"
    )

print("\n抽取后半段与关键帧")
cap = cv2.VideoCapture(str(RUN / "annotated.mp4"))
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"video frames={total}")
for index in [10, 120, 300, 500, 650, 750, 850, 950, 1050, 1150]:
    if index >= total:
        continue
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    if not ok:
        continue
    target = OUT / f"belt2_{index:04d}.png"
    ok, encoded = cv2.imencode(".png", frame)
    if ok:
        target.write_bytes(encoded.tobytes())
        print(f"  wrote {target.relative_to(ROOT)}")
cap.release()
