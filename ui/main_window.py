# -*- coding: utf-8 -*-
"""主窗口：进程附加、热键、五个功能页与日志。"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import paths, saves
from core.debug_flags import DebugFlags
from core.freezer import Freezer
from core.hotkeys import HotkeyManager
from core.presets import ACTION_LABELS
from core.scanner import VALUE_TYPES, Scanner

from . import scaling
from . import theme as theme_mod
from .scaling import px, pxs
from .tab_debug import DebugTab
from .tab_locked import LockedTab
from .tab_onekey import OneKeyTab
from .tab_presets import PresetsTab
from .tab_saves import SavesTab
from .tab_scan import ScanTab

APP_TITLE = "爱丽丝的摇篮 修改器"
APP_VER = "v1.1"

LEVEL_TAGS = {"info": "fg", "ok": "ok", "warn": "warn", "err": "err", "dim": "dim"}

# 标签页顺序：新手只需要第一页，其余是「想深挖时再去」的高级功能
TAB_ORDER = [
    ("onekey", "一键（新手看这里）"),
    ("locked", "锁定 / 监视"),
    ("presets", "预设"),
    ("debug", "调试开关"),
    ("saves", "存档"),
    ("scan", "高级扫描"),
]


def elide_path(path, limit: int = 64) -> str:
    """把长路径掐头留尾，避免把顶栏按钮挤出窗口。"""
    text = str(path)
    if len(text) <= limit:
        return text
    tail = text[-(limit - 12):]
    cut = tail.find("\\")
    return "…" + (tail[cut + 1:] if cut >= 0 else tail)


class TrainerApp(tk.Tk):
    def __init__(self) -> None:
        # DPI 感知必须在创建任何窗口之前声明：晚一步系统就按 96 DPI 渲染
        # 再整体位图放大，界面会发虚。
        scaling.SCALE.awareness = scaling.enable_dpi_awareness()
        super().__init__()
        self.cfg = paths.load_config()
        scaling.apply(self, self.cfg.get("ui_scale", scaling.SETTING_AUTO))
        self.palette = theme_mod.apply(self, self.cfg.get("theme", "dark"))

        self.proc = None
        self.scanner: Scanner | None = None
        self.freezer = Freezer(None)
        self.hotkeys = HotkeyManager()
        self.debug: DebugFlags | None = None
        self.game_dir: Path | None = None
        self._hk_queue: "queue.Queue[str]" = queue.Queue()
        self._detect_q: "queue.Queue[Path | None]" = queue.Queue()
        self._ask_quit = False
        self._relaunching = False
        self._launching = False
        self._auto_tick = 0
        self._auto_failed: set[int] = set()
        self._auto_seen: dict[int, float] = {}
        self._auto_waiting = False

        self.title(f"{APP_TITLE} {APP_VER}")
        self._apply_geometry()

        self._build_header()
        # 先摆底部日志区：pack 是「先摆的先占位置」，日志垫底后才不会被
        # 主区域（标签页的请求高度很大）挤成一个像素
        self._build_log()
        self._build_tabs()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._bootstrap)
        self.after(500, self._tick)

    # ================================================== 窗口尺寸

    def _apply_geometry(self) -> None:
        """优先用上次保存的窗口位置，否则按缩放给一个合适的大小。"""
        (dw, dh), (mw, mh) = scaling.default_geometry()
        self._min_size = (mw, mh)
        saved = scaling.sane_geometry(self.cfg.get("window_geometry", ""), mw, mh)
        if saved:
            self.geometry(saved)
        else:
            self.geometry(f"{dw}x{dh}")
        self.minsize(mw, mh)

    def _reset_window(self) -> None:
        (dw, dh), (mw, mh) = scaling.default_geometry()
        self.cfg["window_geometry"] = ""
        self.save_cfg()
        self.minsize(mw, mh)
        self.geometry(f"{dw}x{dh}+{(scaling.work_area()[0] - dw) // 2}+40")
        self.log(f"窗口尺寸已重置为 {dw}×{dh}（按当前缩放 {scaling.SCALE.percent}% 计算）")

    # ================================================== 界面骨架

    def _build_header(self) -> None:
        head = ttk.Frame(self, style="Bar.TFrame", padding=pxs(14, 8))
        head.pack(fill="x")

        # ---------- 第一行：标题、附加状态、显示相关开关 ----------
        row1 = ttk.Frame(head, style="Bar.TFrame")
        row1.pack(fill="x")
        self.hdr_row1 = row1
        ttk.Label(row1, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        ttk.Label(row1, text=APP_VER, style="Sub.TLabel").pack(side="left", padx=pxs(8, 0))
        self.lb_proc = ttk.Label(row1, text="○ 未附加", style="Sub.TLabel")
        self.lb_proc.pack(side="left", padx=pxs(16, 0))

        self.v_top = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="置顶", variable=self.v_top, style="TCheckbutton",
                        command=self._toggle_top).pack(side="right")
        self.v_hk = tk.BooleanVar(value=bool(self.cfg.get("hotkeys_enabled", True)))
        ttk.Checkbutton(row1, text="启用热键", variable=self.v_hk, style="TCheckbutton",
                        command=self._toggle_hotkeys).pack(side="right", padx=pxs(12, 0))
        ttk.Button(row1, text="重置窗口", command=self._reset_window).pack(
            side="right", padx=pxs(12, 0))
        self.cb_scale = ttk.Combobox(row1, width=7, state="readonly",
                                     values=scaling.CHOICES)
        self.cb_scale.set(scaling.setting_text(self.cfg.get("ui_scale", scaling.SETTING_AUTO)))
        self.cb_scale.pack(side="right", padx=pxs(4, 0))
        self.cb_scale.bind("<<ComboboxSelected>>", lambda _e: self._on_scale_change())
        ttk.Label(row1, text="界面缩放", style="Sub.TLabel").pack(side="right")

        # ---------- 第二行：游戏目录与附加按钮 ----------
        row2 = ttk.Frame(head, style="Bar.TFrame")
        row2.pack(fill="x", pady=pxs(8, 0))
        right = ttk.Frame(row2, style="Bar.TFrame")
        right.pack(side="right")
        self.hdr_buttons = right
        for text, cmd, btn_style in [
            ("选择游戏目录…", self.choose_game_dir, "TButton"),
            ("启动并附加", self.launch_and_attach, "Accent.TButton"),
            ("附加", self.attach, "TButton"),
            ("附加到…", self.attach_to_pid, "TButton"),
            ("切换主题", self.toggle_theme, "TButton"),
        ]:
            ttk.Button(right, text=text, command=cmd, style=btn_style).pack(
                side="left", padx=pxs(3, 0))
        self.lb_game = ttk.Label(row2, text="游戏目录：未设置", style="Sub.TLabel")
        self.lb_game.pack(side="left")

    # ================================================== 界面缩放

    def _on_scale_change(self) -> None:
        from tkinter import messagebox
        choice = self.cb_scale.get()
        value = scaling.setting_value(choice)
        old = self.cfg.get("ui_scale", scaling.SETTING_AUTO)
        if value == old:
            return
        self.cfg["ui_scale"] = value
        self.save_cfg()
        msg = (f"界面缩放已设为「{choice}」。\n\n"
               f"当前渲染：{scaling.SCALE.describe()}\n"
               f"DPI 感知：{scaling.AWARENESS_LABELS.get(scaling.SCALE.awareness, '?')}\n\n"
               f"缩放会改变字体与控件尺寸，需要重启修改器才能重新排版。\n"
               f"现在自动重启吗？")
        if messagebox.askyesno("重启以应用缩放", msg, parent=self):
            self._restart()
        else:
            self.log(f"界面缩放已保存为「{choice}」，下次启动生效"
                     f"（当前仍是 {scaling.SCALE.percent}%）", "warn")

    def _restart(self) -> None:
        """先把新实例拉起来，再关掉自己（退出码不受影响）。"""
        script = Path(__file__).resolve().parent.parent / "aic_trainer.pyw"
        flags = 0
        if os.name == "nt":
            flags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
        try:
            subprocess.Popen([sys.executable, str(script)], cwd=str(script.parent),
                             creationflags=flags, close_fds=True)
        except OSError as exc:
            self.log(f"自动重启失败：{exc}　请手动关闭本窗口后重新打开", "err")
            return
        self.log("正在按新的缩放重启修改器…")
        self._relaunching = True
        self._shutdown()


    def _build_tabs(self) -> None:
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=px(10), pady=pxs(10, 0))

        self.tab_onekey = OneKeyTab(self)
        self.tab_locked = LockedTab(self)
        self.tab_presets = PresetsTab(self)
        self.tab_debug = DebugTab(self)
        self.tab_saves = SavesTab(self)
        self.tab_scan = ScanTab(self)

        self.tabs: dict[str, ttk.Frame] = {
            "onekey": self.tab_onekey,
            "locked": self.tab_locked,
            "presets": self.tab_presets,
            "debug": self.tab_debug,
            "saves": self.tab_saves,
            "scan": self.tab_scan,
        }
        for key, label in TAB_ORDER:
            self.nb.add(self.tabs[key], text=label)
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._on_tab_changed())

    def _build_log(self) -> None:
        p = self.palette
        wrap = ttk.Frame(self, padding=pxs(10, 8, 10, 10))
        wrap.pack(side="bottom", fill="x")
        self.log_wrap = wrap

        bar = ttk.Frame(wrap)
        bar.pack(fill="x")
        self.lb_status = ttk.Label(bar, text="就绪", style="Dim.TLabel")
        self.lb_status.pack(side="left")
        ttk.Button(bar, text="清空日志", command=self._clear_log).pack(side="right")
        ttk.Button(bar, text="复制日志", command=self._copy_log).pack(side="right", padx=px(6))

        box = ttk.Frame(wrap)
        box.pack(fill="x", pady=pxs(6, 0))
        self.log_text = tk.Text(box, height=5, wrap="word", relief="flat",
                                bg=p["panel"], fg=p["fg"], insertbackground=p["fg"],
                                font=("Microsoft YaHei UI", 9), padx=px(8), pady=px(6))
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set, state="disabled")
        self.log_text.tag_configure("fg", foreground=p["fg"])
        self.log_text.tag_configure("ok", foreground=p["ok"])
        self.log_text.tag_configure("warn", foreground=p["warn"])
        self.log_text.tag_configure("err", foreground=p["err"])
        self.log_text.tag_configure("dim", foreground=p["fg_dim"])

    # ================================================== 日志

    def log(self, msg: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {msg}\n", LEVEL_TAGS.get(level, "fg"))
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _copy_log(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.log_text.get("1.0", "end"))
        self.log("日志已复制到剪贴板")

    def set_status(self, text: str) -> None:
        self.lb_status.configure(text=text)

    # ================================================== 启动引导

    def _bootstrap(self) -> None:
        self.log(f"{APP_TITLE} {APP_VER} 已启动（纯本地运行，不联网、不注入）")
        threading.Thread(target=self._detect_game_dir, name="detect", daemon=True).start()
        mode = "深色" if self.cfg.get("theme", "dark") == "dark" else "浅色"
        self.log(f"界面主题：{mode}（可在 config/trainer.json 的 theme 字段切换）", "dim")
        s = scaling.SCALE
        self.log(f"显示：{s.describe()}；DPI 感知："
                 f"{scaling.AWARENESS_LABELS.get(s.awareness, s.awareness)}", "dim")
        if s.awareness in ("unsupported",) and s.dpi > 96:
            self.log("警告：系统缩放大于 100% 但未能声明 DPI 感知，界面会被系统放大而发虚", "warn")
        self.log(f"可用工作区：{scaling.work_area()[0]}×{scaling.work_area()[1]} 物理像素；"
                 f"窗口 {self.winfo_width()}×{self.winfo_height()}"
                 f"（改缩放走顶栏「界面缩放」）", "dim")
        self._recheck_dpi()
        self._drain_detect_queue()

    def _recheck_dpi(self) -> None:
        """窗口真正落到显示器上之后再看一次 DPI。

        启动瞬间窗口还没绑定显示器时，有时只能读到系统 DPI；把窗口拖到另一块
        缩放比不同的屏幕时 Tk 8.6 也不会自己重排，所以这里如实提示一次。
        """
        now = scaling.current_dpi(self)
        if now and now != scaling.SCALE.dpi:
            self.log(f"提示：当前显示器 DPI 为 {now}（启动时按 {scaling.SCALE.dpi} 排版）。"
                     f"Tk 不会在换屏后自动重排，如需最佳效果请重启修改器。", "warn")

    def _detect_game_dir(self) -> None:
        """后台线程：只做磁盘探测，结果放进队列，由主线程消费（tkinter 非线程安全）。"""
        explicit = self.cfg.get("game_dir", "")
        try:
            found = paths.find_game_dir(explicit)
        except Exception:
            found = None
        self._detect_q.put(found)

    def _drain_detect_queue(self) -> None:
        try:
            while True:
                found = self._detect_q.get_nowait()
                self._set_game_dir(found)
        except queue.Empty:
            pass

    def _set_game_dir(self, found: Path | None) -> None:
        if not found:
            self.lb_game.configure(text="游戏目录：未找到，请手动选择")
            self.log("未自动找到游戏目录，请点右上角「选择游戏目录…」指到 AliceInCradle.exe 所在文件夹", "warn")
            return
        self.game_dir = found
        self.cfg["game_dir"] = str(found)
        self.save_cfg()
        self.lb_game.configure(text="游戏目录：" + elide_path(found))
        self.log(f"游戏目录（完整路径）：{found}", "dim")
        self.debug = DebugFlags(paths.debug_txt(found))
        self.debug.load()
        self.log(f"已定位游戏目录：{found}")
        self.log(f"存档目录：{paths.save_dir()}", "dim")
        self.tab_debug.refresh()
        self.tab_onekey.refresh()

    def choose_game_dir(self) -> None:
        init = str(self.game_dir or Path("D:/"))
        chosen = filedialog.askdirectory(title="选择 AliceInCradle.exe 所在的文件夹",
                                         initialdir=init)
        if not chosen:
            return
        p = Path(chosen)
        if not paths.is_game_dir(p):
            for sub in paths._walk_limited(p, max_depth=3):
                if paths.is_game_dir(sub):
                    p = sub
                    break
        if not paths.is_game_dir(p):
            messagebox.showwarning("目录不对",
                                   "该目录下没有 AliceInCradle.exe 与 AliceInCradle_Data 文件夹。",
                                   parent=self)
            return
        self._set_game_dir(p)

    # ================================================== 附加

    def _current_pid(self) -> int | None:
        if self.proc and self.proc.opened and self.proc.alive():
            return self.proc.pid
        return None

    def attach(self, pid: int | None = None) -> bool:
        from core import winmem
        if pid is None:
            pid = winmem.find_pid_by_name(paths.APP_EXE)
        if not pid:
            self.log("没找到 AliceInCradle.exe 进程 —— 请先启动游戏，或点「启动并附加」", "warn")
            return False

        if self.proc:
            self.proc.close()
        proc = winmem.Process(pid)
        if not proc.open():
            self.log(proc.last_error or "附加失败", "err")
            return False

        self.proc = proc
        vt = self.tab_scan.vtype if self.scanner is None else self.scanner.vt
        self.scanner = Scanner(proc, vt,
                               include_readonly=self.tab_scan.v_ro.get(),
                               include_mapped=self.tab_scan.v_mapped.get())
        self.tab_scan.clear(keep_mode=False)

        self.freezer.set_process(proc)
        self.freezer.start()

        if not proc.is_64bit:
            self.log("注意：目标进程是 32 位，本修改器按 64 位寻址，可能出现异常", "warn")

        mods = proc.modules()
        regs = proc.regions()
        self.log(f"已附加 AliceInCradle.exe（PID {pid}）", "ok")
        self.log(f"模块 {len(mods)} 个，可写内存区域 {len(regs)} 个 / "
                 f"{sum(r.size for r in regs)/1048576:.0f} MB", "dim")
        mono = [m for m in mods if "mono" in m.name.lower()]
        if mono:
            self.log(f"检测到 Mono 运行时：{mono[0].name}（本作是 Unity + Mono，"
                     f"调试开关与内存扫描都可用）", "dim")

        self.lb_proc.configure(text=f"● 已附加 PID {pid}")
        self._launching = False
        self.apply_presets_on_attach()
        self._auto_backup_saves()
        self._start_hotkeys()
        self.tab_locked.refresh()
        return True

    def apply_presets_on_attach(self) -> None:
        presets = self.cfg.get("presets", [])
        if not presets:
            self.log("提示：还没有任何预设。定位到数值后可在「预设」页保存，下次一键套用。", "dim")
            return
        from core import presets as pr
        for p in presets:
            pr.apply_preset(p, self.freezer)
        self.log(f"已自动套用 {len(presets)} 个预设（可在「锁定 / 监视」页停用）", "ok")

    def _auto_backup_saves(self) -> None:
        if not self.cfg.get("autobackup_saves", True):
            return
        target, msg = saves.auto_backup("auto")
        if target:
            self.log("自动备份存档：" + msg, "ok")
            self.tab_saves.refresh()
        else:
            self.log(msg, "dim")

    def attach_to_pid(self) -> None:
        from core import winmem
        procs = sorted(winmem.list_processes(), key=lambda x: x[1].lower())
        items = [f"{pid:>6}  {name}" for pid, name in procs]
        from .tab_presets import _Chooser
        dlg = _Chooser(self, self, "选择要附加的进程", items)
        self.wait_window(dlg)
        if dlg.index is None:
            return
        pid = procs[dlg.index][0]
        self.attach(pid)

    def launch_and_attach(self) -> None:
        if not self.game_dir:
            self.choose_game_dir()
            if not self.game_dir:
                return
        exe = paths.game_exe(self.game_dir)
        if not exe.is_file():
            self.log(f"找不到主程序：{exe}", "err")
            return
        try:
            subprocess.Popen([str(exe)], cwd=str(self.game_dir))
        except OSError as exc:
            self.log(f"启动失败：{exc}", "err")
            return
        self._launching = True          # 期间交给 _wait_for_process，别让自动连接抢
        self.log(f"已启动游戏，正在等待进程出现…（本作加载较慢，请耐心等）")
        self._wait_for_process(0)

    def _wait_for_process(self, tries: int) -> None:
        from core import winmem
        pid = winmem.find_pid_by_name(paths.APP_EXE)
        if pid:
            self._wait_until_ready(pid, 0)
            return
        if tries >= 40:      # ≈ 80 秒
            self._launching = False
            self.log("等待游戏进程超时，请手动点「附加」", "warn")
            return
        self.after(2000, lambda: self._wait_for_process(tries + 1))

    def _wait_until_ready(self, pid: int, tries: int) -> None:
        """等游戏把内存铺开再附加。

        刚启动的游戏进程地址空间几乎是空的（模块 0 个、可写内存 0 MB），
        这时附加进去扫描会一无所获 —— 所以先等它加载完。
        """
        from core import winmem
        if not winmem.find_pid_by_name(paths.APP_EXE):
            self._launching = False
            self.log("游戏进程不见了，请重新点「启动并附加」", "warn")
            return
        if winmem.process_ready(pid) or tries >= 90:      # 最多再等 3 分钟
            if tries:
                self.log(f"游戏加载完成（等了约 {tries * 2} 秒），正在连接…", "dim")
            self.attach(pid)
            return
        if tries == 0:
            self.log("游戏正在加载，等它就绪后再连接…（本作加载比较慢，请稍等）", "dim")
        elif tries % 15 == 0:
            self.log(f"还在等游戏加载…（已等约 {tries * 2} 秒）", "dim")
        self.after(2000, lambda: self._wait_until_ready(pid, tries + 1))

    def _try_auto_attach(self) -> None:
        """游戏一启动就自动连上 —— 新手不用记得点「附加」。"""
        if not self.cfg.get("auto_attach", True) or self._launching:
            return
        if self.proc and self.proc.opened and self.proc.alive():
            return
        from core import winmem
        pid = winmem.find_pid_by_name(paths.APP_EXE)
        if not pid or pid in self._auto_failed:
            return
        # 游戏还在加载就先不连：太早附加会扫不到东西。最多等 60 秒，之后照连不误。
        if not winmem.process_ready(pid):
            first = self._auto_seen.setdefault(pid, time.time())
            if time.time() - first < 60:
                if not self._auto_waiting:
                    self.log("检测到游戏正在启动，等它加载完成后再自动连接…", "dim")
                    self._auto_waiting = True
                return
        self._auto_waiting = False
        self.log("检测到游戏已经在运行，自动连接中…", "dim")
        if not self.attach(pid):
            self._auto_failed.add(pid)      # 同一个进程别反复重试刷屏
            self.log("自动连接失败（可能是权限问题）。可以试试以管理员身份运行本工具，"
                     "或点顶栏「附加」手动重试。", "warn")

    def detach(self) -> None:
        self.freezer.stop()
        if self.proc:
            self.proc.close()
        self.proc = None
        self.freezer.set_process(None)
        self.lb_proc.configure(text="○ 未附加")
        self.log("已断开与游戏的连接（锁定与监视已停止）")

    # ================================================== 热键

    def _start_hotkeys(self) -> None:
        self.hotkeys.stop()
        if not self.v_hk.get():
            self.log("全局热键未启用", "dim")
            return
        failures = self.hotkeys.start(self.cfg.get("hotkeys", {}))
        if failures:
            for action, reason in failures.items():
                self.log(f"热键「{ACTION_LABELS.get(action, action)}」注册失败：{reason}", "warn")
        else:
            mapping = self.cfg.get("hotkeys", {})
            self.log("全局热键已就绪：" + "、".join(
                f"{v}={ACTION_LABELS.get(k, k)}" for k, v in mapping.items()), "ok")
            self.log("提示：F1~F5 会抢占游戏内对应按键，若影响操作可在上方取消「启用热键」", "dim")

    def _toggle_hotkeys(self) -> None:
        self.cfg["hotkeys_enabled"] = bool(self.v_hk.get())
        self.save_cfg()
        if self.v_hk.get():
            self._start_hotkeys()
        else:
            self.hotkeys.stop()
            self.log("已临时停用全部全局热键（游戏内 F1~F5 恢复原样）")

    def _toggle_top(self) -> None:
        self.attributes("-topmost", bool(self.v_top.get()))

    def toggle_theme(self) -> None:
        cur = self.cfg.get("theme", "dark")
        nxt = "light" if cur == "dark" else "dark"
        self.cfg["theme"] = nxt
        self.save_cfg()
        self.log(f"界面主题已切换为{'浅色' if nxt == 'light' else '深色'}，"
                 f"重启修改器后生效（设置已写入 config/trainer.json）", "ok")

    def _handle_hotkey(self, action: str) -> None:
        # 「一键」页找数值时用的两个热键：在游戏里直接告诉工具数值刚才是怎么变的
        if action in ("smaller", "bigger"):
            self.tab_onekey.hotkey_narrow(action == "bigger")
            return

        if action == "add_money":
            e = self.freezer.find_lock_by_slot("add_money")
            if not e:
                self.log("热键「金币 +99999」还没绑定地址 —— 请先在「预设」页为槽位 "
                         "add_money 建立预设", "warn")
                return
            e.value += 99999
            e.enabled = True
            try:
                addr = e.target.resolve(self.freezer._ctx)
                if addr:
                    self.proc.write(addr, e.vtype.pack(e.value))
            except Exception:
                pass
            self.log(f"金币 +99999（当前锁定值 {int(e.value)}）", "ok")
            return

        if action == "speed_cycle":
            e = self.freezer.find_lock_by_slot("speed_cycle")
            if not e:
                self.log("热键「速度倍率」还没绑定地址 —— 请先在「预设」页为槽位 "
                         "speed_cycle 建立预设", "warn")
                return
            steps = [1.0, 1.5, 2.0, 3.0, 5.0]
            cur = float(e.value)
            nxt = next((s for s in steps if s > cur + 1e-6), steps[0])
            e.value = nxt
            e.enabled = True
            self.log(f"速度倍率切换为 ×{nxt:g}（需要该地址本身是速度参数）", "ok")
            return

        e = self.freezer.find_lock_by_slot(action)
        if not e:
            self.log(f"热键「{ACTION_LABELS.get(action, action)}」还没绑定地址 —— "
                     f"请先扫描并锁定该数值，再在「预设」页把槽位设为 {action}", "warn")
            return
        self.freezer.set_lock_enabled(e.uid, not e.enabled)
        self.log(f"「{e.label}」已{'开启' if not e.enabled else '关闭'}"
                 f"（{'启用' if not e.enabled else '停用'}）", "ok")

    # ================================================== 周期刷新

    def _tick(self) -> None:
        if not self._ask_quit:
            self._drain_detect_queue()
            for action in self.hotkeys.poll():
                self._handle_hotkey(action)
            current = self._current_tab()
            if self.freezer._thread and current == "locked":
                self.tab_locked.refresh()
            elif current == "onekey":
                self.tab_onekey.refresh_connection()
            self._auto_tick += 1
            if self._auto_tick >= 8:            # 每 4 秒看一眼游戏有没有启动
                self._auto_tick = 0
                self._try_auto_attach()
            self._update_status()
            self.after(500, self._tick)

    def _update_status(self) -> None:
        parts = []
        if self.proc and self.proc.opened:
            alive = self.proc.alive()
            if not alive:
                self.lb_proc.configure(text="○ 游戏已退出")
            parts.append(f"{'运行中' if alive else '已退出'} PID {self.proc.pid}")
        if self.scanner is not None:
            parts.append(f"候选 {self.scanner.count}")
        nlock = sum(1 for e in self.freezer.locks.values() if e.enabled)
        parts.append(f"锁定中 {nlock}/{len(self.freezer.locks)}")
        parts.append(f"监视 {len(self.freezer.monitors)}")
        if self.game_dir:
            parts.append(str(self.game_dir.name))
        self.set_status("　|　".join(parts))

    def on_scan_changed(self) -> None:
        self._update_status()

    def goto_tab(self, key: str) -> None:
        frame = self.tabs.get(key)
        if frame is not None:
            self.nb.select(frame)

    def _current_tab(self) -> str:
        """按控件身份判断当前是哪一页 —— 比硬编码索引稳，加减页面都不会错位。"""
        cur = self.nb.select()
        for key, frame in self.tabs.items():
            if str(frame) == cur:
                return key
        return ""

    def _on_tab_changed(self) -> None:
        key = self._current_tab()
        if key == "onekey":
            self.tab_onekey.refresh()
        elif key == "locked":
            self.tab_locked.refresh()
        elif key == "presets":
            self.tab_presets.refresh()
        elif key == "saves":
            self.tab_saves.refresh()

    # ================================================== 收尾

    def save_cfg(self) -> None:
        try:
            paths.save_config(self.cfg)
        except OSError as exc:
            self.log(f"配置保存失败：{exc}", "err")

    def _on_close(self) -> None:
        if self._relaunching:
            return
        nlock = sum(1 for e in self.freezer.locks.values() if e.enabled)
        if nlock and not messagebox.askyesno(
                "退出确认", f"还有 {nlock} 个锁定项在生效。\n退出后游戏内数值将不再被按住，"
                            f"确定退出修改器？", parent=self):
            return
        self._shutdown()

    def _shutdown(self) -> None:
        """保存窗口位置并收尾（退出与自动重启共用）。"""
        self._ask_quit = True
        try:
            self.cfg["window_geometry"] = self.geometry()
        except tk.TclError:
            pass
        try:
            self.save_cfg()
            self.freezer.stop()
            self.hotkeys.stop()
            if self.proc:
                self.proc.close()
        finally:
            self.destroy()


def main() -> int:
    app = TrainerApp()
    app.mainloop()
    return 0
