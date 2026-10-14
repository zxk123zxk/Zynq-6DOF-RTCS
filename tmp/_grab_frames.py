"""临时诊断脚本：从两次采集的 annotated.mp4 抽帧，供人工查看现场到底长什么样。"""
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "frames"
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("green_belt", ROOT / "vision_runs" / "绿色传送带" / "annotated.mp4", [5, 60, 120, 200, 300, 450]),
    ("yellow_desk", ROOT / "vision_runs" / "黄色桌面" / "annotated.mp4", [5, 20, 60, 100, 140, 200, 245]),
]

for name, video, indices in TARGETS:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"{name}: cannot open {video}")
        continue
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"{name}: total={total} fps={fps:.2f} size={width}x{height}")
    for index in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            print(f"  frame {index}: read failed")
            continue
        target = OUT / f"{name}_{index:04d}.png"
        ok, encoded = cv2.imencode(".png", frame)
        if ok:
            target.write_bytes(encoded.tobytes())
            print(f"  wrote {target.relative_to(ROOT)}")
    cap.release()
