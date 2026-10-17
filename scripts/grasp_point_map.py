#!/usr/bin/env python3
"""工作平面 (x_mm, y_mm) -> 六轴 target_count 的示教表插值骨架。

在精确逆运动学（两连杆解析解）就绪之前，用**已知示教点**做最近邻或双线性插值，
把视觉映射得到的平面坐标转成机械臂六轴目标。这是"抓取点参数化"的几何层：
approach/grasp/lift 三步里随 (x,y) 变化的是 ID 1-3（位置关节），ID 4-6（姿态/夹爪）
保持固定姿态，从工位计划的基准步取值。

精确解析解接口已留（``map_grasp_analytic``），等工位几何实测后填。

示教点表格式（JSON，每点只存随坐标变的 ID 1-3 目标）：
[
  {"x_mm": 0.0, "y_mm": 0.0, "targets": [t1, t2, t3]},
  ...
]

坐标轴约定：x 向右、y 向前（与 workspace_plane.yaml 的映射输出一致），单位 mm。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable, Optional, Sequence


# 随平面坐标变化的关节（ID 1-3）。ID 4-6 的姿态/夹爪由固定姿态提供。
POSITION_AXES = (1, 2, 3)


def load_table(path: Path) -> list[dict]:
    """读示教点表并做基本校验；点数不足 1 直接抛错。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("teaching table must be a non-empty JSON array")
    out = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            raise ValueError(f"table[{i}] is not an object")
        x, y = p.get("x_mm"), p.get("y_mm")
        targets = p.get("targets")
        if (not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or
                not isinstance(targets, list) or len(targets) != len(POSITION_AXES) or
                not all(isinstance(t, int) for t in targets)):
            raise ValueError(f"table[{i}] must be {{x_mm, y_mm, targets:[3 ints]}}")
        out.append({"x_mm": float(x), "y_mm": float(y), "targets": list(targets)})
    return out


def nearest(x_mm: float, y_mm: float, table: Sequence[dict]) -> dict:
    """最近邻：欧氏距离最小的示教点。"""
    return min(table, key=lambda p: (p["x_mm"] - x_mm) ** 2 + (p["y_mm"] - y_mm) ** 2)


def bilinear(x_mm: float, y_mm: float, table: Sequence[dict]) -> list[int]:
    """双线性插值：取最近 4 个示教点做反距离加权；点数不足 4 退化为最近邻。

    这是示教点分布稀疏时的兜底，不保证误差——真实误差必须用独立验证点实测，
    与平面映射同一口径。"""
    if len(table) < 4:
        return list(nearest(x_mm, y_mm, table)["targets"])
    nearest4 = sorted(table, key=lambda p: (p["x_mm"] - x_mm) ** 2 + (p["y_mm"] - y_mm) ** 2)[:4]
    weights, wsum = [], 0.0
    for p in nearest4:
        d = math.hypot(p["x_mm"] - x_mm, p["y_mm"] - y_mm)
        w = 1.0 / max(d, 1e-6)
        weights.append(w)
        wsum += w
    out = []
    for axis in range(len(POSITION_AXES)):
        num = sum(w * p["targets"][axis] for w, p in zip(weights, nearest4))
        out.append(int(round(num / wsum)))
    return out


def map_grasp(x_mm: float, y_mm: float, table: Sequence[dict],
              fixed_pose: Sequence[int], method: str = "nearest") -> list[int]:
    """(x, y) + 固定姿态 -> 完整六轴 target_count。

    ``fixed_pose`` 是 ID 4-6 的固定目标（长度 3），由工位计划的基准步提供。
    返回 [ID1, ID2, ID3, ID4, ID5, ID6] 六个 target。"""
    if len(fixed_pose) != 6 - len(POSITION_AXES):
        raise ValueError("fixed_pose must cover the non-position axes (length 3)")
    if method == "bilinear":
        pos = bilinear(x_mm, y_mm, table)
    elif method == "nearest":
        pos = list(nearest(x_mm, y_mm, table)["targets"])
    else:
        raise ValueError("method must be 'nearest' or 'bilinear'")
    return pos + list(fixed_pose)


def map_grasp_analytic(x_mm: float, y_mm: float, link_lengths: Iterable[float],
                       fixed_pose: Sequence[int]) -> list[int]:
    """精确两连杆解析解——留待工位几何实测后实现。

    link_lengths: 从基座到抓取平面所需的连杆长度参数（单位与坐标系定义待定）。
    未实现前调用即抛错，绝不返回猜测值。"""
    raise NotImplementedError(
        "analytic IK requires measured link geometry; use teaching-table "
        "interpolation until then")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", type=Path)
    parser.add_argument("--x-mm", type=float, required=True)
    parser.add_argument("--y-mm", type=float, required=True)
    parser.add_argument("--fixed-pose", type=lambda s: [int(v) for v in s.split(",")],
                        required=True, help="ID4,ID5,ID6 固定目标，逗号分隔")
    parser.add_argument("--method", choices=("nearest", "bilinear"), default="nearest")
    args = parser.parse_args()
    t = load_table(args.table)
    print(json.dumps({"x_mm": args.x_mm, "y_mm": args.y_mm,
                      "method": args.method,
                      "target_count": map_grasp(args.x_mm, args.y_mm, t,
                                               args.fixed_pose, args.method)},
                     ensure_ascii=False))
