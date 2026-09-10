# -*- coding: utf-8 -*-
"""扫描页：首扫 / 再筛选 / 写入 / 锁定 / 监视 / 邻域浏览。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core.freezer import Target
from core.scanner import (BETWEEN, EXACT, FIRST_MODES, NEXT_MODES, Scanner,
                          TYPE_ORDER, UNKNOWN, VALUE_TYPES, fmt_value, parse_value)

from .scaling import px, pxs
from .widgets import (ask_values, attach_scroll, card, fmt_addr, fmt_num, make_tree,
                      run_async, tag_rows)


MAX_ROWS = 5000          # 表格最多显示多少行
AUTO_TYPES = ["byte", "2bytes", "4bytes", "8bytes"]


class ScanTab(ttk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app, padding=px(10))
        self.app = app
        self.task = None
        self.rows: dict[str, int] = {}     # tree iid -> address
        self._build()
        self.refresh_mode()

    # -------------------------------------------------- 构建

    def _build(self) -> None:
        top, body = card(self, "")
        top.pack(fill="x")

        grid = ttk.Frame(body, style="Card.TFrame")
        grid.pack(fill="x")

        ttk.Label(grid, text="数值类型", style="DimCard.TLabel").grid(row=0, column=0, sticky="w")
        self.cb_type = ttk.Combobox(grid, width=14, state="readonly",
                                    values=[VALUE_TYPES[k].label for k in TYPE_ORDER])
        self.cb_type.current(TYPE_ORDER.index("4bytes"))
        self.cb_type.grid(row=1, column=0, sticky="w", padx=pxs(0, 10))
        self.cb_type.bind("<<ComboboxSelected>>", lambda _e: self._on_type_change())

        ttk.Label(grid, text="扫描方式", style="DimCard.TLabel").grid(row=0, column=1, sticky="w")
        self.cb_mode = ttk.Combobox(grid, width=16, state="readonly", values=FIRST_MODES)
        self.cb_mode.current(0)
        self.cb_mode.grid(row=1, column=1, sticky="w", padx=pxs(0, 10))
        self.cb_mode.bind("<<ComboboxSelected>>", lambda _e: self._on_mode_change())

        ttk.Label(grid, text="数值", style="DimCard.TLabel").grid(row=0, column=2, sticky="w")
        self.e_value = ttk.Entry(grid, width=20)
        self.e_value.grid(row=1, column=2, sticky="w", padx=pxs(0, 10))
        self.e_value.bind("<Return>", lambda _e: self.do_scan())

        ttk.Label(grid, text="结束值", style="DimCard.TLabel").grid(row=0, column=3, sticky="w")
        self.e_value2 = ttk.Entry(grid, width=20, state="disabled")
        self.e_value2.grid(row=1, column=3, sticky="w", padx=pxs(0, 10))

        btns = ttk.Frame(grid, style="Card.TFrame")
        btns.grid(row=1, column=4, sticky="w", padx=pxs(6, 0))
        self.btn_scan = ttk.Button(btns, text="开始扫描", style="Accent.TButton",
                                   command=self.do_scan)
        self.btn_scan.pack(side="left")
        self.btn_cancel = ttk.Button(btns, text="取消", state="disabled",
                                     command=self.do_cancel)
        self.btn_cancel.pack(side="left", padx=px(6))
        ttk.Button(btns, text="清除结果", command=self.clear).pack(side="left")

        opts = ttk.Frame(body, style="Card.TFrame")
        opts.pack(fill="x", pady=pxs(10, 0))
        self.v_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="智能扫描（精确值模式下自动尝试 1/2/4/8 字节）",
                        variable=self.v_auto, style="Card.TCheckbutton").pack(side="left")
        self.v_float = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="连浮点一起试", variable=self.v_float,
                        style="Card.TCheckbutton").pack(side="left", padx=pxs(14, 0))
        self.v_ro = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="包含只读内存", variable=self.v_ro,
                        style="Card.TCheckbutton",
                        command=self._apply_region_opts).pack(side="left", padx=pxs(14, 0))
        self.v_mapped = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="包含映射内存(慢)", variable=self.v_mapped,
                        style="Card.TCheckbutton",
                        command=self._apply_region_opts).pack(side="left", padx=pxs(14, 0))

        # ---------------- 结果 ----------------
        mid, mbody = card(self, "")
        mid.pack(fill="both", expand=True, pady=pxs(10, 0))

        head = ttk.Frame(mbody, style="Card.TFrame")
        head.pack(fill="x")
        self.lb_summary = ttk.Label(head, text="尚无结果 —— 先附加游戏，再输入数值扫描",
                                    style="Card.TLabel")
        self.lb_summary.pack(side="left")
        self.pb = ttk.Progressbar(head, length=px(200), mode="determinate", maximum=1.0)
        self.pb.pack(side="right")
        self.lb_progress = ttk.Label(mbody, text="", style="DimCard.TLabel")
        self.lb_progress.pack(anchor="w", pady=pxs(4, 6))

        wrap = ttk.Frame(mbody, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.tree = make_tree(wrap, [
            ("idx", "#", 60), ("addr", "地址", 170), ("value", "当前值", 130),
            ("type", "类型", 110), ("state", "状态", 140),
        ], height=14)
        self.tree.pack(side="left", fill="both", expand=True)
        attach_scroll(self.tree, wrap).pack(side="right", fill="y")
        tag_rows(self.tree, self.app.palette)
        self.tree.bind("<Double-1>", lambda _e: self.write_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_selection_hint())

        actions = ttk.Frame(mbody, style="Card.TFrame")
        actions.pack(fill="x", pady=pxs(8, 0))
        for text, cmd in [
            ("写入选中…", self.write_selected),
            ("锁定选中", self.lock_selected),
            ("加入监视", self.monitor_selected),
            ("邻域浏览…", self.browse_selected),
            ("复制地址", self.copy_selected),
            ("移出列表", self.remove_selected),
        ]:
            ttk.Button(actions, text=text, command=cmd).pack(side="left", padx=pxs(0, 6))

        self.lb_hint = ttk.Label(mbody, text="", style="DimCard.TLabel")
        self.lb_hint.pack(anchor="w", pady=pxs(6, 0))

    # -------------------------------------------------- 状态联动

    @property
    def vtype(self):
        return VALUE_TYPES[TYPE_ORDER[self.cb_type.current()]]

    def _on_type_change(self) -> None:
        if self.app.scanner:
            self.app.scanner.set_type(self.vtype)
            self.app.log(f"数值类型切换为 {self.vtype.label}，已清空候选列表")
        self.clear(keep_mode=True)

    def _on_mode_change(self) -> None:
        mode = self.cb_mode.get()
        need_two = mode == BETWEEN
        self.e_value2.configure(state="normal" if need_two else "disabled")
        first = mode in FIRST_MODES
        self.btn_scan.configure(text="开始扫描" if first else "再筛选")
        self.e_value.configure(state="normal")

    def _apply_region_opts(self) -> None:
        if self.app.scanner:
            self.app.scanner.include_readonly = self.v_ro.get()
            self.app.scanner.include_mapped = self.v_mapped.get()

    def refresh_mode(self) -> None:
        has = bool(self.app.scanner and self.app.scanner.count)
        modes = NEXT_MODES if has else FIRST_MODES
        cur = self.cb_mode.get()
        self.cb_mode.configure(values=modes)
        if cur not in modes:
            self.cb_mode.current(0)
        self._on_mode_change()

    def _set_busy(self, busy: bool) -> None:
        self.btn_scan.configure(state="disabled" if busy else "normal")
        self.btn_cancel.configure(state="normal" if busy else "disabled")

    def _update_selection_hint(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self.lb_hint.configure(text="")
            return
        addrs = [self.rows[i] for i in sel if i in self.rows]
        self.lb_hint.configure(
            text=f"已选中 {len(addrs)} 项；首个地址 {fmt_addr(addrs[0])}"
            if addrs else "")

    # -------------------------------------------------- 扫描

    def do_scan(self) -> None:
        app = self.app
        if not (app.proc and app.proc.opened):
            app.log("请先「启动并附加」或「附加」游戏进程", "warn")
            return
        mode = self.cb_mode.get()
        vt = self.vtype

        try:
            if mode == UNKNOWN or mode in ("变化了", "未变化", "增加了", "减少了"):
                v1 = v2 = None
            else:
                v1 = parse_value(self.e_value.get(), vt)
                v2 = parse_value(self.e_value2.get(), vt) if mode == BETWEEN else None
        except ValueError as exc:
            app.log(str(exc), "err")
            return

        sc = app.scanner
        auto = mode == EXACT and self.v_auto.get() and not sc.count
        types = list(AUTO_TYPES)
        if auto and self.v_float.get():
            types += ["float", "double"]

        sc.include_readonly = self.v_ro.get()
        sc.include_mapped = self.v_mapped.get()

        self._set_busy(True)
        self.pb.configure(value=0.0)

        def work(progress, cancelled):
            if auto:
                report = []
                best = None
                for i, key in enumerate(types):
                    tmp = Scanner(app.proc, VALUE_TYPES[key],
                                  sc.include_readonly, sc.include_mapped)
                    try:
                        val = parse_value(self.e_value.get(), tmp.vt)
                    except ValueError:
                        continue
                    n = tmp.first_scan(EXACT, val,
                                       progress=lambda f, t, i=i: progress(
                                           (i + f) / len(types),
                                           f"[{VALUE_TYPES[key].label}] {t}"),
                                       cancelled=cancelled)
                    report.append((key, n))
                    if n and (best is None or n < best[1]):
                        best = (key, n, tmp, val)
                    if cancelled():
                        break
                if best is None:
                    return sc, report, None
                return best[2], report, best[3]

            if mode in FIRST_MODES:
                n = sc.first_scan(mode, v1, v2, progress=progress, cancelled=cancelled)
            else:
                n = sc.next_scan(mode, v1, v2, progress=progress, cancelled=cancelled)
            return sc, None, None

        self.task = run_async(self, work,
                              on_done=self._scan_done,
                              on_error=self._scan_error,
                              on_progress=self._scan_progress)

    def _scan_progress(self, frac: float, text: str) -> None:
        self.pb.configure(value=max(0.0, min(1.0, frac)))
        self.lb_progress.configure(text=text)

    def _scan_error(self, exc: Exception) -> None:
        self._set_busy(False)
        self.lb_progress.configure(text="")
        self.app.log(f"扫描失败：{exc!r}", "err")

    def _scan_done(self, result) -> None:
        self._set_busy(False)
        self.pb.configure(value=1.0 if self.pb["value"] else 0)
        sc, report, matched_value = result
        if sc is not self.app.scanner:
            self.app.scanner = sc

        if report:
            summary = "、".join(f"{VALUE_TYPES[k].label}:{n}" for k, n in report)
            hits = [(k, n) for k, n in report if n]
            self.lb_progress.configure(text=f"智能扫描结果 —— {summary}")
            if hits:
                self.app.log(f"智能扫描命中：{summary}")
            else:
                self.app.log("所有类型都没命中，建议改用「未知初始值」扫描", "warn")

        self.reload_rows()

    def do_cancel(self) -> None:
        if self.task:
            self.task.cancel()
            self.app.log("已请求取消扫描…", "warn")

    def clear(self, keep_mode: bool = False) -> None:
        if self.app.scanner:
            self.app.scanner.clear()
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        if not keep_mode:
            self.refresh_mode()
        self.lb_summary.configure(text="结果已清空")
        self.lb_progress.configure(text="")
        self.pb.configure(value=0.0)
        if not keep_mode:
            self.app.log("已清空扫描结果")

    # -------------------------------------------------- 结果表

    def reload_rows(self) -> None:
        sc = self.app.scanner
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        if sc is None:
            return
        vt = sc.vt
        pairs = sc.read_snapshot(limit=MAX_ROWS)
        for i, (addr, val) in enumerate(pairs):
            iid = self.tree.insert("", "end", values=(
                i + 1, fmt_addr(addr), fmt_value(vt, val), vt.label, "",
            ), tags=("odd",) if i % 2 else ())
            self.rows[iid] = addr

        total = sc.count
        extra = "" if total <= MAX_ROWS else f"（仅显示前 {MAX_ROWS} 行）"
        self.lb_summary.configure(
            text=f"命中 {total} 个地址{extra}    数值类型：{vt.label}"
            + ("    ⚠ 已达上限，结果被截断" if sc.truncated else ""))
        self.refresh_mode()
        self.app.on_scan_changed()

    # -------------------------------------------------- 操作

    def _selected_addrs(self) -> list[int]:
        return [self.rows[i] for i in self.tree.selection() if i in self.rows]

    def write_selected(self) -> None:
        app = self.app
        addrs = self._selected_addrs()
        if not addrs:
            app.log("请先在结果表里选中要写入的行", "warn")
            return
        cur = ""
        if len(addrs) == 1 and app.scanner:
            v = app.scanner.read_one(addrs[0])
            cur = str(v) if v is not None else ""
        ok, raw, _ = ask_values(self, "写入数值",
                                f"将写入 {len(addrs)} 个地址：", cur, palette=app.palette)
        if not ok:
            return
        try:
            value = parse_value(raw, app.scanner.vt)
        except ValueError as exc:
            app.log(str(exc), "err")
            return
        done = sum(1 for a in addrs if app.scanner.write(a, value))
        app.log(f"已写入 {done}/{len(addrs)} 个地址 = {raw}")
        self.reload_rows()

    def lock_selected(self) -> None:
        app = self.app
        addrs = self._selected_addrs()
        if not addrs:
            app.log("请先在结果表里选中要锁定的行", "warn")
            return
        vt = app.scanner.vt
        default = ""
        v = app.scanner.read_one(addrs[0])
        if v is not None:
            default = str(v)
        ok, raw, _ = ask_values(self, "锁定数值",
                                f"把 {len(addrs)} 个地址锁定为：", default,
                                palette=app.palette)
        if not ok:
            return
        try:
            value = parse_value(raw, vt)
        except ValueError as exc:
            app.log(str(exc), "err")
            return
        for i, a in enumerate(addrs):
            label = f"扫描项 {fmt_addr(a)}" if len(addrs) == 1 else f"扫描项 {i+1}@{fmt_addr(a)}"
            app.freezer.add_lock(label, Target(kind="direct", addr=a), vt, value)
        app.log(f"已锁定 {len(addrs)} 个地址 = {raw}（在「锁定/监视」页可调）")
        app.goto_tab("locked")

    def monitor_selected(self) -> None:
        app = self.app
        addrs = self._selected_addrs()
        if not addrs:
            app.log("请先选中要监视的行", "warn")
            return
        vt = app.scanner.vt
        for i, a in enumerate(addrs[:50]):
            app.freezer.add_monitor(f"监视 {fmt_addr(a)}", Target(kind="direct", addr=a), vt)
        app.log(f"已加入监视 {min(len(addrs), 50)} 项")
        app.goto_tab("locked")

    def browse_selected(self) -> None:
        app = self.app
        addrs = self._selected_addrs()
        if not addrs:
            app.log("请先选中一行再查看邻域", "warn")
            return
        sc = app.scanner
        pairs = sc.browse(addrs[0], span=512)
        if not pairs:
            app.log("邻域读取失败", "err")
            return
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        target = addrs[0]
        for i, (a, v) in enumerate(pairs):
            mark = "  ← 目标" if a == target else ""
            iid = self.tree.insert("", "end", values=(
                i + 1, fmt_addr(a), fmt_value(sc.vt, v), sc.vt.label, mark,
            ), tags=("hit",) if a == target else (("odd",) if i % 2 else ()))
            self.rows[iid] = a
        self.lb_summary.configure(
            text=f"邻域浏览：{fmt_addr(target)} 前后 512 字节，共 {len(pairs)} 个 {sc.vt.label} 槽位"
                 "（适合一次找出相邻的 HP/MP/EP）")
        app.log(f"邻域浏览 {fmt_addr(target)}，列出 {len(pairs)} 个候选")

    def copy_selected(self) -> None:
        addrs = self._selected_addrs()
        if not addrs:
            return
        text = "\n".join(fmt_addr(a) for a in addrs)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.app.log(f"已复制 {len(addrs)} 个地址到剪贴板")

    def remove_selected(self) -> None:
        for iid in self.tree.selection():
            addr = self.rows.pop(iid, None)
            self.tree.delete(iid)
            if addr is not None and self.app.scanner:
                try:
                    idx = self.app.scanner.addrs.index(addr)
                    del self.app.scanner.addrs[idx]
                    del self.app.scanner.prev[idx]
                except (ValueError, IndexError):
                    pass
        self.app.on_scan_changed()

    def load_addresses(self, addrs: list[int]) -> None:
        """供预设页/锁定页跳转回来显示。"""
        sc = self.app.scanner
        if not sc or not addrs:
            return
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        for i, a in enumerate(addrs):
            v = sc.read_one(a)
            iid = self.tree.insert("", "end", values=(
                i + 1, fmt_addr(a), fmt_value(sc.vt, v), sc.vt.label, "",
            ), tags=("odd",) if i % 2 else ())
            self.rows[iid] = a
        self.lb_summary.configure(text=f"显示 {len(addrs)} 个地址")
