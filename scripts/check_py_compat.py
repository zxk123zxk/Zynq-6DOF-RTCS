#!/usr/bin/env python3
"""扫板端脚本里 Python 3.12 才允许的语法，避免"本地能跑、板上直接 SyntaxError"。

板端 PetaLinux 2023.2 是 Python 3.10/3.11，开发机是 3.13。最常踩的一处是
**f-string 里嵌套同类引号**（PEP 701，3.12 起才合法）：双引号定界的 f-string 里，
花括号内又写一对双引号（通常是为了塞一个三元表达式），3.11 下整个文件语法错误。

本地 `py_compile` 通过，板上 arm 一启动就崩：runner 两百毫秒退出、一行 `G3_` 输出都没有，
`GRASP_RESULT` 里 `success=None fault=None`——看着像"什么都没发生"，其实文件根本没被载入。
2026-10-29 实际踩到一次，白跑一趟上板。

用法：
    python3 scripts/check_py_compat.py scripts/*.py     # 有命中则退出码 1
被 `stage_sd_payload.sh` 当告警（不阻断打包）、被 `sim/run_g3_station_runner_guard.sh`
当断言（必须为 0）。

只查这一件事：逐行找 f-string，看 `{...}` 里是否出现与字符串定界符相同的引号。
刻意保持简单——它对"跨行 f-string"和转义检测不强，但这几类在本仓库的写法里不出现，
而漏报只会让检查失效、不会让好文件被误判。
"""
from __future__ import annotations

import sys
from pathlib import Path

QUOTES = "\"'"


def scan_line(line: str):
    """返回该行里"嵌套同类引号"的列号列表。"""
    hits = []
    index = 0
    while index < len(line):
        char = line[index]
        # f" 或 f' 开头（前面不能是标识符字符，否则 buf" 会被误认）
        if char in "fF" and index + 1 < len(line) and line[index + 1] in QUOTES:
            previous = line[index - 1] if index else " "
            if previous.isalnum() or previous == "_":
                index += 1
                continue
            quote = line[index + 1]
            depth = 0
            cursor = index + 2
            while cursor < len(line):
                current = line[cursor]
                if current == "{" and depth == 0:
                    depth = 1
                elif current == "}" and depth:
                    depth = 0
                elif current == quote:
                    if depth:
                        hits.append(cursor + 1)
                    else:
                        break
                cursor += 1
            index = cursor
        index += 1
    return hits


def check_file(path: Path) -> int:
    """逐个文件扫描；返回命中数。"""
    hits = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        print("PY_COMPAT_ERROR %s: %s" % (path, error), file=sys.stderr)
        return 0
    for number, line in enumerate(text.splitlines(), start=1):
        for column in scan_line(line):
            hits += 1
            print("PY_COMPAT_HIT %s:%d:%d  f-string 里嵌套了同种引号，"
                  "板端 Python<=3.11 会 SyntaxError" % (path, number, column))
    return hits


def main(argv=None) -> int:
    paths = [Path(item) for item in (argv if argv is not None else sys.argv[1:])]
    if not paths:
        print("用法：check_py_compat.py <file.py> [more.py ...]", file=sys.stderr)
        return 2
    total = sum(check_file(path) for path in paths)
    if total:
        print("PY_COMPAT_FAIL hits=%d（改法：把三元表达式提成局部变量，或改用 %% 格式化）"
              % total, file=sys.stderr)
        return 1
    print("PY_COMPAT_OK files=%d" % len(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
