# -*- coding: utf-8 -*-
"""高 DPI 支持：声明进程 DPI 感知，并把「设计像素」换算成实际像素。

为什么需要这个模块
------------------
Windows 在「显示缩放」大于 100% 时，对**没有声明 DPI 感知**的进程会做两件事：
把系统 API 报告的坐标按缩放比例缩小（虚拟化），再让桌面窗口管理器把整个
窗口的位图**放大**回物理像素。

结果就是：2560×1440 的屏幕，程序实际只用 1707×960 的分辨率在画，画完再被
拉伸 1.5 倍——文字笔画、表格竖线、小图标全部经过插值，发虚、发毛。

本模块做两件事：
1. 在建任何窗口之前**声明每显示器 DPI 感知 v2**，让系统按物理像素渲染；
2. 提供一个缩放因子：字体靠 Tk 自己的 `tk scaling`（point → pixel）放大，
   而 padding、行高、列宽、窗口尺寸这些**以像素为单位**的数值由 `px()`
   统一换算，保证界面整体等比放大而不是只有字变大。

缩放倍率可由配置里的 `ui_scale` 控制："auto" 跟随系统，或指定 "125%" / 1.5 等。
"""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform.startswith("win")

# DPI_AWARENESS_CONTEXT 常量（值为 -4 / -3 / -2 的伪句柄）
_CTX_PER_MONITOR_V2 = -4
_CTX_PER_MONITOR = -3
_CTX_SYSTEM = -2

_ERROR_ACCESS_DENIED = 5
_E_ACCESSDENIED = 0x80070005

AWARENESS_LABELS = {
    "per-monitor-v2": "每显示器感知 v2（最佳）",
    "per-monitor": "每显示器感知",
    "system": "系统级感知",
    "already": "已声明（由运行环境设置）",
    "unsupported": "未声明（界面会被系统放大，会发虚）",
    "non-windows": "非 Windows",
}

SETTING_AUTO = "auto"
CHOICES = ["自动", "100%", "110%", "125%", "150%", "175%", "200%"]

_GEOM_RE = re.compile(r"^(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?$")


# ==================================================== Win32 探测

def enable_dpi_awareness() -> str:
    """声明进程 DPI 感知。必须在创建 Tk 窗口之前调用。

    返回实际生效的级别（见 AWARENESS_LABELS 的键）。重复调用是安全的。
    """
    if not IS_WINDOWS:
        return "non-windows"
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    # 1) 每显示器感知 v2（Win10 1703+），支持跨屏自动切换
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(_CTX_PER_MONITOR_V2)):
            return "per-monitor-v2"
        if ctypes.get_last_error() == _ERROR_ACCESS_DENIED:
            return "already"          # 已经被别处（如宿主进程）设过了
    except AttributeError:
        pass

    # 2) 每显示器感知（Win8.1+）
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        hr = shcore.SetProcessDpiAwareness(2)
        if hr == 0:
            return "per-monitor"
        if hr == _E_ACCESSDENIED:
            return "already"
    except (OSError, AttributeError):
        pass

    # 3) 系统级感知（Vista+）
    try:
        if user32.SetProcessDPIAware():
            return "system"
    except AttributeError:
        pass
    return "unsupported"


def current_dpi(root=None) -> int:
    """取窗口所在显示器的 DPI（96 = 100%）。"""
    if not IS_WINDOWS:
        return 96
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    if root is not None:
        try:
            user32.GetDpiForWindow.argtypes = [wintypes.HWND]
            user32.GetDpiForWindow.restype = wintypes.UINT
            value = int(user32.GetDpiForWindow(root.winfo_id()))
            if value:
                return value
        except Exception:
            pass

    try:
        user32.GetDpiForSystem.restype = wintypes.UINT
        value = int(user32.GetDpiForSystem())
        if value:
            return value
    except AttributeError:
        pass

    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    hdc = user32.GetDC(0)
    try:
        return int(gdi.GetDeviceCaps(hdc, 88)) or 96      # LOGPIXELSX
    finally:
        user32.ReleaseDC(0, hdc)


class _RECT(ctypes.Structure):
    _fields_ = [("l", wintypes.LONG), ("t", wintypes.LONG),
                ("r", wintypes.LONG), ("b", wintypes.LONG)]


def work_area() -> tuple[int, int]:
    """主显示器可用工作区（物理像素，已扣除任务栏）。"""
    if not IS_WINDOWS:
        return 1920, 1080
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    rc = _RECT()
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rc), 0):   # SPI_GETWORKAREA
        w, h = rc.r - rc.l, rc.b - rc.t
        if w > 200 and h > 200:
            return w, h
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


# ==================================================== 缩放

class Scale:
    """界面缩放状态。

    语义：`factor` 就是**界面实际倍数**（相对 96 DPI 基准）。
    - `ui_scale = "auto"` → factor = 系统 DPI / 96，即跟随 Windows 显示缩放；
    - `ui_scale = "150%"`、`1.5` → factor = 1.5，与系统设置无关，所见即所得。
    """

    def __init__(self) -> None:
        self.dpi = 96
        self.auto = True
        self.user = 1.0
        self.factor = 1.0
        self.awareness = "unsupported"

    # ---------------------------------------- 换算

    def px(self, value) -> int:
        return int(round(float(value) * self.factor))

    def pxs(self, *values) -> tuple:
        """一串像素值一起换算，便于 padding=(a, b) 这类用法。"""
        return tuple(int(round(float(v) * self.factor)) for v in values)

    @property
    def percent(self) -> int:
        return int(round(self.factor * 100))

    def describe(self) -> str:
        mode = "自动跟随系统" if self.auto else f"手动 {self.user * 100:.0f}%"
        return (f"DPI {self.dpi}（系统缩放 {self.dpi / 96 * 100:.0f}%）"
                f" × {mode} → 界面 {self.percent}%")


SCALE = Scale()


def px(value) -> int:
    return SCALE.px(value)


def pxs(*values) -> tuple:
    return SCALE.pxs(*values)


# ---------------------------------------- 配置解析

def parse_setting(raw) -> tuple[bool, float]:
    """把配置里的 ui_scale 解析为 (是否自动, 手动倍率)。"""
    if raw is None or raw == "" or (isinstance(raw, str)
                                    and raw.strip() in (SETTING_AUTO, "自动", "auto")):
        return True, 1.0
    if isinstance(raw, bool):
        return True, 1.0
    if isinstance(raw, (int, float)):
        user = float(raw)
    else:
        try:
            user = float(str(raw).strip().rstrip("%").strip())
        except ValueError:
            return True, 1.0
    if user > 10:              # 写成 150 时按百分比理解
        user /= 100.0
    return False, max(0.5, min(4.0, user))


def setting_text(raw) -> str:
    """配置值 → 界面下拉框里的文字。"""
    auto, user = parse_setting(raw)
    if auto:
        return "自动"
    for item in CHOICES:
        if item == "自动":
            continue
        if abs(float(item.rstrip("%")) / 100 - user) < 1e-6:
            return item
    return f"{user * 100:.0f}%"


def setting_value(text: str):
    """界面下拉框的文字 → 配置值。"""
    if text == "自动":
        return SETTING_AUTO
    return round(float(text.rstrip("%")) / 100.0, 4)


# ---------------------------------------- 应用

def resolve_factor(raw_setting, dpi: int) -> tuple[bool, float, float]:
    """把 ui_scale 解析成 (是否自动, 手动倍率, 最终倍数)。"""
    auto, user = parse_setting(raw_setting)
    factor = max(0.5, min(4.0, dpi / 96.0 if auto else user))
    return auto, user, factor


def apply(root, raw_setting) -> Scale:
    """按配置设置 root 的 Tk 缩放，并刷新模块级缩放因子。

    必须在创建任何控件之前调用：Tk 的字体是按 point 定义的，
    `tk scaling` = 每 point 多少像素，改晚了已建好的控件不会跟着变。

    字体走 Tk 自己的换算（10pt 在 96 DPI 下是 13.33px），所以要让字体也放大
    factor 倍，`tk scaling` 取 (96/72) × factor —— 与 px() 用的是同一个 factor，
    字号与间距因此严格同步。
    """
    dpi = current_dpi(root)
    auto, user, factor = resolve_factor(raw_setting, dpi)
    SCALE.dpi = dpi
    SCALE.auto = auto
    SCALE.user = user
    SCALE.factor = factor
    try:
        root.tk.call("tk", "scaling", 96.0 / 72.0 * factor)
    except Exception:
        pass
    return SCALE


# ---------------------------------------- 窗口尺寸

def default_geometry(base_w: int = 1200, base_h: int = 860,
                     min_w: int = 1000, min_h: int = 640
                     ) -> tuple[tuple[int, int], tuple[int, int]]:
    """返回 (默认尺寸, 最小尺寸)，按当前缩放放大并夹进可用工作区。

    最小尺寸额外收到工作区的 60%：缩放调到 200% 时不该把最小窗口顶到整屏，
    否则用户再也没法把窗口改小。
    """
    aw, ah = work_area()
    w = min(SCALE.px(base_w), int(aw * 0.96))
    h = min(SCALE.px(base_h), int(ah * 0.96))
    mw = max(480, min(SCALE.px(min_w), int(aw * 0.6), w))
    mh = max(360, min(SCALE.px(min_h), int(ah * 0.6), h))
    return (w, h), (mw, mh)


def sane_geometry(text: str, min_w: int, min_h: int) -> str | None:
    """校验并夹紧保存下来的窗口几何串（换屏、改缩放后仍要能看见）。"""
    match = _GEOM_RE.match((text or "").strip())
    if not match:
        return None
    aw, ah = work_area()
    w = max(min_w, min(int(match.group(1)), int(aw * 0.98)))
    h = max(min_h, min(int(match.group(2)), int(ah * 0.98)))
    if match.group(3) is None:
        return f"{w}x{h}"
    x, y = int(match.group(3)), int(match.group(4))
    x = max(-w + 160, min(x, aw - 160))
    y = max(0, min(y, ah - 80))
    return f"{w}x{h}{x:+d}{y:+d}"
