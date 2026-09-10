# -*- coding: utf-8 -*-
"""全局热键（RegisterHotKey + 独立消息循环线程）。

RegisterHotKey(hwnd=NULL, ...) 会把 WM_HOTKEY 投递到「调用它的线程」的消息队列，
因此注册与消息循环必须在同一个线程内完成。
命中后把动作名放进 queue.Queue，由 UI 主线程轮询执行（tkinter 非线程安全）。
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                      ctypes.c_void_p, ctypes.c_void_p]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

VK_NAMED = {
    "SPACE": 0x20, "TAB": 0x09, "ESC": 0x1B, "ESCAPE": 0x1B, "ENTER": 0x0D, "RETURN": 0x0D,
    "BACKSPACE": 0x08, "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PGUP": 0x21, "PRIOR": 0x21, "PGDN": 0x22, "NEXT": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "`": 0xC0, "BACKQUOTE": 0xC0, "GRAVE": 0xC0,
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF,
}
for _i in range(1, 25):
    VK_NAMED[f"F{_i}"] = 0x6F + _i


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+1' -> (mods, vk)。无法解析时抛 ValueError。"""
    if not text or not text.strip():
        raise ValueError("热键为空")
    parts = [p.strip() for p in text.replace("＋", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError("热键为空")
    mods = 0
    vk = None
    for part in parts:
        low = part.lower()
        if low in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif low == "alt":
            mods |= MOD_ALT
        elif low == "shift":
            mods |= MOD_SHIFT
        elif low in ("win", "super"):
            mods |= MOD_WIN
        else:
            key = part.upper()
            if key in VK_NAMED:
                vk = VK_NAMED[key]
            elif len(key) == 1 and key.isalnum():
                vk = ord(key)
            else:
                raise ValueError(f"无法识别的按键：{part}")
    if vk is None:
        raise ValueError("热键缺少主键（如 F1、Ctrl+1）")
    return mods | MOD_NOREPEAT, vk


class HotkeyManager:
    def __init__(self) -> None:
        self.events: "queue.Queue[str]" = queue.Queue()
        self.failures: dict[str, str] = {}
        self.enabled = False
        self._mapping: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._ids: dict[int, str] = {}
        self._next_id = 0xA100

    # -------------------------------------------------- 对外接口

    def mapping(self) -> dict[str, str]:
        return dict(self._mapping)

    def start(self, mapping: dict[str, str]) -> dict[str, str]:
        """注册并启动；返回注册失败的动作 -> 原因。"""
        self.stop()
        self._mapping = dict(mapping)
        self.failures = {}
        self._ids = {}
        self._next_id = 0xA100
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._thread.join(timeout=1.5)   # 等注册结果
        return dict(self.failures)

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=1.0)
        self._thread = None
        self.enabled = False

    def set_enabled(self, enabled: bool) -> dict[str, str]:
        if enabled:
            return self.start(self._mapping)
        self.stop()
        return {}

    def poll(self) -> list[str]:
        """取出自上次调用以来触发的动作名列表。"""
        out: list[str] = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                break
        return out

    # -------------------------------------------------- 线程主体

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        for action, key in self._mapping.items():
            try:
                mods, vk = parse_hotkey(key)
            except ValueError as exc:
                self.failures[action] = str(exc)
                continue
            hid = self._next_id
            self._next_id += 1
            if user32.RegisterHotKey(None, hid, mods, vk):
                self._ids[hid] = action
            else:
                self.failures[action] = f"注册失败（错误码 {ctypes.get_last_error()}，可能被其他程序占用）"
        self.enabled = True

        msg = wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                action = self._ids.get(int(msg.wParam))
                if action:
                    self.events.put(action)

        for hid in list(self._ids):
            user32.UnregisterHotKey(None, hid)
        self._ids.clear()
        self.enabled = False
