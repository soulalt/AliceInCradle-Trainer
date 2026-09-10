# -*- coding: utf-8 -*-
"""P6 自测：真实构建界面 + 附加真实进程 + 逐页跑一遍操作。

冒烟测试不验证像素，只确保：窗口能建起来、各页刷新不报错、核心链路（附加→扫描→锁定→
预设→热键回调）在界面上下文中能跑通。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 配置隔离到临时目录：自测不该写脏用户真实的 config/trainer.json
os.environ["AIC_CONFIG_DIR"] = tempfile.mkdtemp(prefix="aic_test_cfg_")

from ui.widgets import ScrollArea             # noqa: E402  （仅导入，不建窗口）

GAME_DIR = os.environ.get("AIC_GAME_DIR") or os.path.dirname(ROOT)

# 这些测试要对着真实游戏跑；不在游戏目录里就直说，别让人对着莫名其妙的报错发呆
if not os.path.isfile(os.path.join(GAME_DIR, "AliceInCradle.exe")):
    print(f"[跳过] 找不到游戏目录：{GAME_DIR}")
    print("       请把本工具放在游戏根目录下（与 AliceInCradle.exe 同级），"
          "或设置环境变量 AIC_GAME_DIR 指向游戏目录。")
    raise SystemExit(2)


fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def pump(app, times: int = 6, delay: float = 0.05) -> None:
    """刷新事件循环；带真实 sleep，好让后台锁定线程/探测线程有机会跑。"""
    for _ in range(times):
        app.update_idletasks()
        app.update()
        time.sleep(delay)


def wait_until(app, cond, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        pump(app, 1, 0.05)
        if cond():
            return True
    return False


def clipped_widgets(tab, kind) -> list:
    """找出超出所在页面可视区域的控件。

    缩放放大后最容易出的一类问题：容器请求高度大于实际可用高度，Tk 会把
    最后摆放的控件截掉（按钮点不到）。滚动区内部按设计可超出，跳过不计。
    """
    out = []

    def walk(w):
        for child in w.winfo_children():
            if isinstance(child, ScrollArea):
                continue
            if isinstance(child, kind):
                bottom = child.winfo_rooty() - tab.winfo_rooty() + child.winfo_height()
                right = child.winfo_rootx() - tab.winfo_rootx() + child.winfo_width()
                if bottom > tab.winfo_height() + 1 or right > tab.winfo_width() + 1:
                    text = child.cget("text") if "text" in child.keys() else child.winfo_class()
                    out.append(str(text))
            walk(child)

    walk(tab)
    return out


def main() -> int:
    from core import paths
    cfg = paths.load_config()
    cfg["game_dir"] = GAME_DIR
    cfg["hotkeys_enabled"] = False        # 冒烟测试不抢占 F1~F5
    cfg["autobackup_saves"] = False       # 避免测试期间反复备份
    cfg["auto_attach"] = False            # 别自动连到用户正在玩的游戏
    cfg["ui_scale"] = "auto"              # 固定用自动缩放，便于断言
    cfg["window_geometry"] = ""           # 忽略上次保存的窗口位置
    cfg["presets"] = []
    paths.save_config(cfg)

    from ui.main_window import TrainerApp
    from ui import dialogs, scaling, widgets
    from tkinter import ttk

    try:
        app = TrainerApp()
        check("主窗口创建成功", True)
    except Exception as exc:
        traceback.print_exc()
        check("主窗口创建成功", False, repr(exc))
        return 1

    pump(app, 10)
    check("六个功能页都已挂载", len(app.nb.tabs()) == 6, f"{len(app.nb.tabs())} 页")
    check("默认停在「一键」页（新手第一眼看到的就是这一页）",
          app._current_tab() == "onekey", app._current_tab())
    check("每个页面都能按名字跳到",
          all(app.tabs.get(k) is not None for k in
              ("onekey", "scan", "locked", "presets", "debug", "saves")),
          str(sorted(app.tabs)))
    check("「一键」页列出了 5 个游戏开关按钮",
          len(app.tab_onekey._flag_buttons) == 5,
          str(list(app.tab_onekey._flag_buttons)))
    check("「一键」页给出了「现在是多少」的提示",
          "是多少" in app.tab_onekey.lb_ask.cget("text"),
          app.tab_onekey.lb_ask.cget("text"))
    check("「一键」页默认锁定量来自用途预设",
          app.tab_onekey.e_lock.get() == "999999", app.tab_onekey.e_lock.get())

    # ---------------- DPI / 缩放 ----------------
    s = scaling.SCALE
    check("已声明 DPI 感知", s.awareness in ("per-monitor-v2", "per-monitor", "system",
                                            "already", "non-windows"), s.awareness)
    check("缩放因子已按 DPI 计算", abs(s.factor - s.dpi / 96.0) < 1e-6,
          f"DPI {s.dpi} → {s.percent}%")
    check("界面缩放下拉框存在且为自动",
          app.cb_scale.get() == "自动", app.cb_scale.get())
    check("像素换算与缩放因子一致", scaling.px(10) == round(10 * s.factor),
          f"px(10)={scaling.px(10)}")
    row_h = int(ttk.Style(app).lookup("Treeview", "rowheight") or 0)
    check("表头行高已缩放", row_h == scaling.px(23), f"{row_h}（期望 {scaling.px(23)}）")

    # 顶栏按钮必须完整落在窗口内（长游戏路径曾把右侧按钮挤出边界）
    app.update_idletasks()
    win_w = app.winfo_width()
    rb = app.hdr_buttons
    right_edge = rb.winfo_rootx() - app.winfo_rootx() + rb.winfo_width()
    check("顶栏按钮未被挤出窗口", right_edge <= win_w, f"按钮右边界 {right_edge} / 窗口 {win_w}")
    check("窗口不小于最小尺寸",
          win_w >= app._min_size[0] or win_w == 1,
          f"{win_w}x{app.winfo_height()} 最小 {app._min_size}")

    got_dir = wait_until(app, lambda: app.game_dir is not None, timeout=10)
    check("自动定位到游戏目录", got_dir and paths.is_game_dir(app.game_dir),
          str(app.game_dir))
    check("_debug.txt 已加载", app.debug is not None and len(app.debug.values()) >= 10,
          f"{len(app.debug.values()) if app.debug else 0} 个开关")
    app.goto_tab("locked")    # 切到「锁定 / 监视」页，让周期刷新走到该页

    # ---------------- 各页刷新 ----------------
    for name, fn in [("扫描页", app.tab_scan.refresh_mode),
                     ("锁定页", app.tab_locked.refresh),
                     ("预设页", app.tab_presets.refresh),
                     ("调试页", app.tab_debug.refresh),
                     ("存档页", app.tab_saves.refresh)]:
        try:
            fn()
            pump(app, 2)
            check(f"{name}刷新无异常", True)
        except Exception as exc:
            traceback.print_exc()
            check(f"{name}刷新无异常", False, repr(exc))

    # 缩放后最容易出的问题：某一页的按钮被容器截掉（点不到）
    for name, tab in [("一键页", app.tab_onekey), ("扫描页", app.tab_scan),
                      ("锁定页", app.tab_locked), ("预设页", app.tab_presets),
                      ("调试页", app.tab_debug), ("存档页", app.tab_saves)]:
        app.nb.select(tab)
        pump(app, 4)
        miss = clipped_widgets(tab, ttk.Button)
        check(f"{name}所有按钮都在可视区内", not miss, "、".join(miss[:4]) or "完整")
    app.goto_tab("locked")
    pump(app, 2)

    # 内容超高的页面必须能滚动，否则下面的按钮点不到
    def has_scroll_area(tab) -> bool:
        stack = [tab]
        while stack:
            node = stack.pop()
            if isinstance(node, ScrollArea):
                return True
            stack.extend(node.winfo_children())
        return False

    for name, tab in [("一键页", app.tab_onekey), ("调试页", app.tab_debug)]:
        check(f"{name}做成了可滚动区域", has_scroll_area(tab))

    # 日志区必须真的看得见（曾经被主区域挤成 1 像素）
    log_h = app.log_text.winfo_height()
    check("底部日志区可见且高度合理", log_h >= scaling.px(40),
          f"日志文本框高 {log_h}px（期望 ≥ {scaling.px(40)}）")
    check("窗口内各区块不越界",
          app.log_wrap.winfo_y() + app.log_wrap.winfo_height() <= app.winfo_height() + 1,
          f"{app.log_wrap.winfo_y() + app.log_wrap.winfo_height()} / {app.winfo_height()}")

    # ---------------- 附加真实子进程 ----------------
    child = subprocess.Popen(
        [sys.executable, "-u", os.path.join(ROOT, "tests", "_child_probe.py")],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        addr = int(child.stdout.readline().strip(), 16)
        ok = app.attach(child.pid)
        pump(app, 4)
        check("界面上附加真实进程成功", ok)
        check("扫描器已就绪", app.scanner is not None and app.freezer._ctx is not None)
        check("锁定线程已启动", app.freezer._thread is not None and app.freezer._thread.is_alive())

        # 扫描（子进程缓冲区内放的是 0x1A2B3C4D）
        app.tab_scan.e_value.delete(0, "end")
        app.tab_scan.e_value.insert(0, "439041101")
        sc = app.scanner
        n = sc.first_scan("精确值", 439041101)
        app.tab_scan.reload_rows()
        pump(app, 3)
        check("界面扫描出结果", n > 0 and len(app.tab_scan.rows) > 0, f"命中 {n}")

        # 锁定
        from core.freezer import Target
        e = app.freezer.add_lock("测试HP", Target(kind="direct", addr=addr), sc.vt, 12345)
        app.tab_locked.refresh()
        pump(app, 12)
        check("锁定表在界面上可见", len(app.tab_locked.lock_rows) >= 1,
              f"{len(app.tab_locked.lock_rows)} 行")

        # 管道里积压了锁定前打印的旧值，一路读到出现 12345 为止
        val, deadline = None, time.time() + 4
        while time.time() < deadline:
            line = child.stdout.readline().strip()
            if not line:
                break
            val = line
            if line == "12345":
                break
        check("界面锁定生效（子进程回读）", val == "12345", f"读到 {val}")

        # 监视
        app.freezer.add_monitor("测试监视", Target(kind="direct", addr=addr), sc.vt)
        pump(app, 8)
        app.tab_locked.refresh()
        pump(app, 2)
        check("监视表在界面上可见", len(app.tab_locked.mon_rows) >= 1,
              f"{len(app.tab_locked.mon_rows)} 行")

        # 预设
        from core import presets as pr
        preset = pr.make_preset("测试预设", Target(kind="direct", addr=addr), sc.vt,
                                999, slot="invincible")
        app.cfg["presets"] = pr.replace_or_add(app.cfg.get("presets", []), preset)
        app.tab_presets.refresh()
        pump(app, 3)
        check("预设页显示预设", len(app.tab_presets.rows) >= 1)
        app.tab_presets.tree.selection_set(list(app.tab_presets.rows)[0])
        app.tab_presets.apply_selected()
        pump(app, 3)
        check("套用预设后锁定表出现对应槽位",
              app.freezer.find_lock_by_slot("invincible") is not None)

        # 热键回调（不依赖真实按键）
        app._handle_hotkey("invincible")
        app._handle_hotkey("add_money")
        app._handle_hotkey("speed_cycle")
        pump(app, 2)
        check("热键回调不崩溃且能切换槽位状态",
              app.freezer.find_lock_by_slot("invincible") is not None)

        # 邻域浏览
        app.tab_scan.tree.selection_set(list(app.tab_scan.rows)[0])
        app.tab_scan.browse_selected()
        pump(app, 2)
        check("邻域浏览可用", len(app.tab_scan.rows) > 0, f"{len(app.tab_scan.rows)} 行")

        # 对话框能构建
        for name, maker in [
            ("数值输入对话框", lambda: widgets.ValueDialog(
                app, "测试", "值：", "1", palette=app.palette)),
            ("锁定项对话框", lambda: dialogs.LockDialog(app, app, "测试")),
            ("预设编辑对话框", lambda: dialogs.PresetDialog(app, app, preset)),
        ]:
            try:
                d = maker()
                d.update_idletasks()
                d.destroy()
                check(f"{name}可构建", True)
            except Exception as exc:
                traceback.print_exc()
                check(f"{name}可构建", False, repr(exc))

        # 停用全部锁定，避免退出确认弹窗
        app.tab_locked.disable_all()
        pump(app, 3)
        check("全部停用后锁定项均为停用态",
              all(not x.enabled for x in app.freezer.locks.values()))
    finally:
        child.kill()
        child.wait(timeout=5)

    app._ask_quit = True
    try:
        app.freezer.stop()
        app.hotkeys.stop()
        if app.proc:
            app.proc.close()
        app.destroy()
        check("窗口正常销毁", True)
    except Exception as exc:
        check("窗口正常销毁", False, repr(exc))

    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
