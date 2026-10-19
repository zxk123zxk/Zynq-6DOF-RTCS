#!/usr/bin/env python3
"""核对 PL 综合进 bitstream 的硬限位与 config 里的实测限位表是否一致。

这是 2026-10-17 那个坑的护栏：示教把 ID2/ID4 的实测可达点改宽了，只同步了
``config/g2_measured_limits.toml``，``g2_board_limits_pkg.sv`` 没跟着改，
板端 ``move-six`` 就在 CHECK_GUARD 阶段以 fault=12 直接拒发——现象是"示教成功、
状态机跑不动"。两份表必须同源同步，这里做机器校验。

注意 SystemVerilog 的打包赋值字面量是"高位在前"：``SAFE_MIN = {a, b, ...}``
里第一个数落在 index 5（即 ID 6）。本脚本按"源码顺序读入再反转"还原成 ID 1..6。

用法：python3 scripts/check_limit_sync.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src/pl/rtl/g2_board_limits_pkg.sv"
TOML = ROOT / "config/g2_measured_limits.toml"
AXES = range(1, 7)


def fail(message: str) -> None:
    print(f"LIMIT_SYNC_FAIL {message}", file=sys.stderr)
    raise SystemExit(1)


def literals(block: str, label: str) -> list[int]:
    """六元素字面量按源码顺序读入后反转成 ID 1..6（SV 打包字面量高位在前）。"""
    values = [int(v) for v in re.findall(r"\d+'d(\d+)", block)]
    if len(values) != 6:
        fail(f"{label}: expected 6 entries, found {len(values)}")
    return list(reversed(values))


def pkg_vector(text: str, name: str) -> list[int]:
    match = re.search(rf"{name}\s*=\s*\{{(.*?)\}}", text, re.S)
    if not match:
        fail(f"{PKG.name}: {name} not found")
    return literals(match.group(1), f"{PKG.name} {name}")


def wrapper_vector(text: str, name: str, label: str) -> list[int] | None:
    """BD 包装层用 .G2_SAFE_MAX({...}) 形式复制一份字面量；没有这一项返回 None。"""
    match = re.search(rf"{name}\s*\(\s*\{{(.*?)\}}\s*\)", text, re.S)
    if not match:
        return None
    return literals(match.group(1), f"{label} {name}")


def pkg_scalar(text: str, name: str) -> int:
    match = re.search(rf"{name}\s*=\s*\d+'([hd])([0-9a-fA-F_]+)", text)
    if not match:
        fail(f"{PKG.name}: {name} not found")
    base = 16 if match.group(1) == "h" else 10
    return int(match.group(2).replace("_", ""), base)


def toml_axes(text: str) -> dict[int, dict[str, int]]:
    axes: dict[int, dict[str, int]] = {}
    current: dict[str, int] | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line == "[[axis]]":
            current = {}
            continue
        if line.startswith("["):
            current = None
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in ("servo_id", "safe_min", "safe_max"):
            try:
                current[key] = int(value.strip())
            except ValueError:
                fail(f"{TOML.name}: {key} is not an integer")
            if key == "servo_id":
                axes[current[key]] = current
    if set(axes) != set(AXES):
        fail(f"{TOML.name}: expected six unique servo_id entries, got {sorted(axes)}")
    return axes


def main() -> int:
    pkg_text = PKG.read_text(encoding="utf-8")
    toml_text = TOML.read_text(encoding="utf-8")

    if pkg_scalar(pkg_text, "CALIBRATED_MASK") != 0x3F:
        fail("CALIBRATED_MASK must be 6'h3f; move-six refuses uncalibrated axes")
    safe_min = pkg_vector(pkg_text, "SAFE_MIN")
    safe_max = pkg_vector(pkg_text, "SAFE_MAX")
    speed_max = pkg_scalar(pkg_text, "SPEED_MAX_RAW")
    axes = toml_axes(toml_text)

    problems = []
    for axis in AXES:
        expected = axes[axis]
        for field, actual in (("safe_min", safe_min[axis - 1]),
                              ("safe_max", safe_max[axis - 1])):
            if expected[field] != actual:
                problems.append(f"ID {axis} {field}: toml={expected[field]} pl={actual}")
        if not safe_min[axis - 1] <= safe_max[axis - 1]:
            problems.append(f"ID {axis}: SAFE_MIN > SAFE_MAX in PL")
    motion = re.search(r"\[motion\](.*?)(?:\n\[|\Z)", toml_text, re.S)
    if motion:
        match = re.search(r"speed_raw_max\s*=\s*(\d+)", motion.group(1))
        if match and int(match.group(1)) != speed_max:
            problems.append(f"speed_raw_max: toml={match.group(1)} pl={speed_max}")

    # BD 包装层（production 是 TTL 版）把限位复制成字面量，必须一起校验，
    # 否则改了 pkg 重综合出来的 bitstream 仍是旧限位，板端 fault=12 拒发。
    wrappers = sorted((ROOT / "src/pl/rtl").glob("rtcs_axi_wrapper*.v"))
    checked = []
    for wrapper in wrappers:
        text = wrapper.read_text(encoding="utf-8")
        if "G2_SAFE_MAX" not in text:
            continue
        label = wrapper.name
        checked.append(label)
        values = {"safe_min": wrapper_vector(text, "G2_SAFE_MIN", label),
                  "safe_max": wrapper_vector(text, "G2_SAFE_MAX", label)}
        for field, vector in values.items():
            if vector is None:
                problems.append(f"{label}: {field} override missing")
                continue
            for axis in AXES:
                if vector[axis - 1] != axes[axis][field]:
                    problems.append(
                        f"{label} ID {axis} {field}: toml={axes[axis][field]} "
                        f"wrapper={vector[axis - 1]}")

    if problems:
        for problem in problems:
            print(f"LIMIT_SYNC_MISMATCH {problem}", file=sys.stderr)
        fail("PL hard limits and config table disagree; resynthesize after fixing the pkg")
    print("LIMIT_SYNC_OK axes=6 speed_raw_max=" + str(speed_max)
          + " sources=" + PKG.name + "+" + TOML.name
          + ("+" + ",".join(checked) if checked else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
