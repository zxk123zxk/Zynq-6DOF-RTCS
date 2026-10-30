"""非阻塞按键：循环一直跑的时候还能按一下就把程序停掉。

不按 q 就永远运行是最自然的工作方式，但 `input()` 会把整个循环卡住，所以这里用
`msvcrt.kbhit()` 轮询——只在 Windows 上有效；其它平台退化成"永远没有按键"，
不影响主流程（那时用 Ctrl-C 退出）。

只给 PC 侧脚本用，**不进板端载荷**。
"""
from __future__ import annotations

try:
    import msvcrt
except ImportError:                 # 非 Windows：没有键盘轮询，靠 Ctrl-C
    msvcrt = None


def poll() -> list[str]:
    """取走当前所有待处理按键（转小写）；没有按键返回空列表。"""
    if msvcrt is None:
        return []
    keys: list[str] = []
    while msvcrt.kbhit():
        try:
            char = msvcrt.getwch()
        except Exception:           # 控制台被抢走/关闭时不值得让整个循环崩掉
            break
        if char:
            keys.append(char.lower())
    return keys
