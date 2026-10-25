#!/usr/bin/env python3
"""工作平面 (x_mm, y_mm) -> 六轴 target_count 的示教表插值骨架。

在精确逆运动学（两连杆解析解）就绪之前，用**已知示教点**做最近邻或双线性插值，
把视觉映射得到的平面坐标转成机械臂六轴目标。这是"抓取点参数化"的几何层：
approach/grasp/lift 三步里随 (x,y) 变化的是 ID 1-3（位置关节），ID 4-6（姿态/夹爪）
保持固定姿态，从工位计划的基准步取值。

精确解析解接口已留（``map_grasp_analytic``），等工位几何实测后填。

示教点表格式（JSON）。每点的 ``targets`` 支持两种轴数：

  * **五轴**（推荐）：``[ID1, ID2, ID3, ID4, ID5]`` —— 机械臂五个关节全部按点实测、
    全部参与插值。教点时的腕部姿态直接沿用，不会出现"教的姿态和跑的姿态不一致"。
  * **三轴**（旧格式，向后兼容）：``[ID1, ID2, ID3]`` —— ID4/ID5 取工位计划的固定值。
    只有在所有点确实共用同一腕部姿态时才成立，否则运行时末端会偏一个姿态。

**ID6（夹爪开度）永远不参与插值**：它是执行器指令，闭合后由接触位置 ``hold`` 接管；
开度取工位计划里该步的值。

[
  {"x_mm": 0.0, "y_mm": 0.0, "targets": [t1, t2, t3, t4, t5]},
  ...
]

坐标轴约定（必须与视觉侧 `config/calibration.json` 完全一致，否则整体偏转）：
原点 = **传送带左下角**，`+x` 沿传送带长度方向，`+y` 沿宽度方向，单位 mm。
（2026-10-21 更正：旧注释写的"x 向右、y 向前"是早期工作台假设，已作废。）
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable, Optional, Sequence


# 位置关节 ID 1-3。姿态关节 ID 4-5 在五轴表里也参与插值（见 SUPPORTED_AXIS_COUNTS）。
POSITION_AXES = (1, 2, 3)
# 允许的 targets 轴数：3 = 只插 ID1-3（旧格式）；5 = 插 ID1-5（推荐）。
# ID6 恒不插值，由工位计划提供。
SUPPORTED_AXIS_COUNTS = (3, 5)


def load_table(path: Path) -> list[dict]:
    """读示教点表并做基本校验；点数不足 1 直接抛错。

    每点必填 ``targets``（ID1-3 或 ID1-5 的**抓取**姿态）；可选 ``lift_targets``
    （**抬升**姿态）。抬升姿态与抓取姿态的关系是非线性的（取决于基座角），所以逐点
    实测才可靠。

    **全表必须同一轴数**：三轴点和五轴点混在一起时，同一列会既表示 ID4 又表示"没有"，
    语义无法消歧，所以直接拒绝而不是猜。
    """
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
                not isinstance(targets, list) or len(targets) not in SUPPORTED_AXIS_COUNTS or
                not all(isinstance(t, int) for t in targets)):
            raise ValueError(f"table[{i}] must be {{x_mm, y_mm, targets:[3 or 5 ints]}}")
        point = {"x_mm": float(x), "y_mm": float(y), "targets": list(targets)}
        lift = p.get("lift_targets")
        if lift is not None:
            if (not isinstance(lift, list) or len(lift) != len(targets) or
                    not all(isinstance(t, int) for t in lift)):
                raise ValueError(f"table[{i}].lift_targets must be "
                                 f"a list of {len(targets)} ints")
            point["lift_targets"] = list(lift)
        out.append(point)
    counts = {len(p["targets"]) for p in out}
    if len(counts) != 1:
        raise ValueError(f"table mixes {sorted(counts)}-axis points; "
                         f"全表必须同一轴数（三轴与五轴混用无法消歧），请统一后重试")
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
    n_axes = len(nearest4[0]["targets"])
    for axis in range(n_axes):
        num = sum(w * p["targets"][axis] for w, p in zip(weights, nearest4))
        out.append(int(round(num / wsum)))
    return out


def same_lane(table: Sequence[dict], tol_mm: float = 8.0, ratio: float = 0.25) -> bool:
    """所有示教点是否落在同一条车道。

    判据取**相对门槛**：``y 起伏 <= max(tol_mm, ratio * x 跨度)``。

    为什么不用绝对 5 mm：教点时物块是手工摆的，y 很自然会有几毫米起伏；而门槛
    一旦判失败，插值会静默退回 :func:`bilinear`——三点表在 bilinear 下等于最近邻，
    误差可达间距一半（10-22 实测 25 mm 间距 → 最坏 ±13 mm，方块夹不住）。
    这是一个**没有报错的降级**，必须让门槛跟示教区间同量级而不是硬编码。
    真正的二维网格（y 跨度和 x 跨度同量级）仍然会判成非车道。
    """
    ys = [p["y_mm"] for p in table]
    xs = [p["x_mm"] for p in table]
    return (max(ys) - min(ys)) <= max(tol_mm, ratio * (max(xs) - min(xs)))


def piecewise_linear(x_mm: float, table: Sequence[dict]) -> list[int]:
    """沿 x 的分段线性插值：**两端外保持端点值（不外推）**。

    这条路径是为"所有示教点同一条车道、只沿 +x 变化"的实务工况准备的。
    它比 :func:`bilinear` 正确：三点都在同一 y 上时，2D 反距离加权没有意义
    （任何查询点的 y 都等于车道 y，权重只由 |Δx| 决定，等于把最近两点的比例
    打平），而抓取姿态对 x 本来就是近似线性的。

    **点数 ≥2 就能用**——这是它相对 bilinear（<4 点退化为最近邻）的关键差别：
    3 点表在 bilinear 下是纯最近邻（误差可达间距一半），在这里是两段直线。
    """
    pts = sorted(table, key=lambda p: p["x_mm"])
    if len(pts) == 1 or x_mm <= pts[0]["x_mm"]:
        return list(pts[0]["targets"])
    if x_mm >= pts[-1]["x_mm"]:
        return list(pts[-1]["targets"])
    for lo, hi in zip(pts, pts[1:]):
        if lo["x_mm"] <= x_mm <= hi["x_mm"]:
            span = hi["x_mm"] - lo["x_mm"]
            t = 0.0 if span <= 0 else (x_mm - lo["x_mm"]) / span
            return [int(round(lo["targets"][i] + t * (hi["targets"][i] - lo["targets"][i])))
                    for i in range(len(lo["targets"]))]
    return list(pts[-1]["targets"])  # 理论上不可达


def map_grasp(x_mm: float, y_mm: float, table: Sequence[dict],
              fixed_pose: Sequence[int], method: str = "auto") -> list[int]:
    """(x, y) + 夹爪开度 -> 完整六轴 target_count。

    ``fixed_pose`` 是 ID4/ID5/ID6 三个计划值（长度 3），来自工位计划的基准步。它的用处
    取决于表的轴数：

      * 五轴表 → **只用它里面的 ID6**（夹爪开度）；ID4/ID5 由表插值，即教点时的腕部姿态。
      * 三轴表 → 三个都用，即 ID4/ID5/ID6 全取计划固定姿态（旧行为）。

    ``method="auto"``（默认）：示教点同车道 → 沿 x 分段线性；否则退回 bilinear。
    返回 [ID1, ID2, ID3, ID4, ID5, ID6] 六个 target。
    """
    if len(fixed_pose) != 6 - len(POSITION_AXES):
        raise ValueError("fixed_pose must cover the non-position axes (length 3)")
    n_axes = len(table[0]["targets"])
    if method == "auto":
        method = "linear" if same_lane(table) else "bilinear"
    if method == "linear":
        pos = piecewise_linear(x_mm, table)
    elif method == "bilinear":
        pos = bilinear(x_mm, y_mm, table)
    elif method == "nearest":
        pos = list(nearest(x_mm, y_mm, table)["targets"])
    else:
        raise ValueError("method must be 'auto', 'linear', 'nearest' or 'bilinear'")
    if n_axes == 5:
        return pos + [fixed_pose[2]]           # ID1-5 插值，ID6 取计划开度
    return pos + list(fixed_pose)              # ID1-3 插值，ID4-6 取计划姿态


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
    parser.add_argument("--method", choices=("auto", "linear", "nearest", "bilinear"),
                        default="auto")
    args = parser.parse_args()
    t = load_table(args.table)
    print(json.dumps({"x_mm": args.x_mm, "y_mm": args.y_mm,
                      "method": args.method,
                      "target_count": map_grasp(args.x_mm, args.y_mm, t,
                                               args.fixed_pose, args.method)},
                     ensure_ascii=False))
