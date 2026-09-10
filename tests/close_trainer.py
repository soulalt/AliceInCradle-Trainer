# -*- coding: utf-8 -*-
"""收尾小工具：列出/关闭「爱丽丝的摇篮 修改器」的窗口。

给脚本化测试用 —— 启动修改器后不需要手动点关闭。

    python tests/close_trainer.py            # 列出并关闭
    python tests/close_trainer.py --list     # 只列出，不关闭

也可以被别的测试 `import close_trainer` 后调用 find_windows() / close_all()。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

TITLE_KEY = "爱丽丝的摇篮 修改器"
WM_CLOSE = 0x0010

u32 = ctypes.WinDLL("user32", use_last_error=True)
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_windows(key: str = TITLE_KEY) -> list[tuple[int, int, str]]:
    """返回 [(hwnd, pid, 标题), ...]。"""
    found: list[tuple[int, int, str]] = []

    def cb(hwnd, _lp):
        n = u32.GetWindowTextLengthW(hwnd)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            if key in buf.value:
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                found.append((hwnd, pid.value, buf.value))
        return True

    u32.EnumWindows(_EnumProc(cb), 0)
    return found


def close_all(key: str = TITLE_KEY) -> int:
    wins = find_windows(key)
    for hwnd, _pid, _title in wins:
        u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return len(wins)


def main() -> int:
    found = find_windows()
    if not found:
        print("没有找到修改器窗口")
        return 0
    for hwnd, pid, title in found:
        print(f"窗口 hwnd={hwnd} pid={pid} title={title}")
    if "--list" not in sys.argv:
        close_all()
        print(f"已向 {len(found)} 个窗口发送关闭请求")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
