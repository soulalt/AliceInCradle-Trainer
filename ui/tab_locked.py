# -*- coding: utf-8 -*-
"""锁定/监视页：查看锁定项与实时监视值，支持手动建立地址与指针链。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core.freezer import Target, parse_target
from core.scanner import TYPE_ORDER, VALUE_TYPES, fmt_value, parse_value

from .scaling import px, pxs
from .widgets import attach_scroll, card, fmt_addr, make_tree, tag_rows


class LockedTab(ttk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app, padding=px(10))
        self.app = app
        self.lock_rows: dict[str, int] = {}
        self.mon_rows: dict[str, int] = {}
        self._build()

    # -------------------------------------------------- 构建

    def _build(self) -> None:
        # ---------------- 锁定表 ----------------
        top, body = card(self, "锁定中（每 100ms 自动回写，游戏内数值会被按住）")
        top.pack(fill="both", expand=True)

        wrap = ttk.Frame(body, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.tree = make_tree(wrap, [
            ("on", "启用", 60), ("name", "名称", 200), ("type", "类型", 110),
            ("target", "地址 / 来源", 260), ("value", "锁定值", 120),
            ("writes", "写入次数", 90), ("state", "状态", 220),
        ], height=9)
        self.tree.pack(side="left", fill="both", expand=True)
        attach_scroll(self.tree, wrap).pack(side="right", fill="y")
        tag_rows(self.tree, self.app.palette)
        self.tree.bind("<Double-1>", lambda _e: self.edit_value())

        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill="x", pady=pxs(8, 0))
        for text, cmd in [
            ("新建锁定…", self.new_lock),
            ("修改锁定值…", self.edit_value),
            ("启用 / 停用", self.toggle_enabled),
            ("删除", self.remove_lock),
            ("全部停用", self.disable_all),
        ]:
            ttk.Button(btns, text=text, command=cmd).pack(side="left", padx=pxs(0, 6))

        # ---------------- 监视表 ----------------
        bot, bbody = card(self, "监视中（只读，用来盯着数值变化 —— 定位未知值就靠它）")
        bot.pack(fill="both", expand=True, pady=pxs(10, 0))

        wrap2 = ttk.Frame(bbody, style="Card.TFrame")
        wrap2.pack(fill="both", expand=True)
        self.mtree = make_tree(wrap2, [
            ("name", "名称", 200), ("type", "类型", 110),
            ("target", "地址 / 来源", 260), ("value", "当前值", 140),
            ("prev", "上一个值", 140), ("state", "状态", 180),
        ], height=8)
        self.mtree.pack(side="left", fill="both", expand=True)
        attach_scroll(self.mtree, wrap2).pack(side="right", fill="y")
        tag_rows(self.mtree, self.app.palette)

        btns2 = ttk.Frame(bbody, style="Card.TFrame")
        btns2.pack(fill="x", pady=pxs(8, 0))
        for text, cmd in [
            ("新建监视…", self.new_monitor),
            ("把监视值送进锁定…", self.monitor_to_lock),
            ("删除", self.remove_monitor),
            ("全部清除", self.clear_monitors),
        ]:
            ttk.Button(btns2, text=text, command=cmd).pack(side="left", padx=pxs(0, 6))

    # -------------------------------------------------- 刷新

    def refresh(self) -> None:
        locks, mons = self.app.freezer.snapshot()

        seen = set()
        for i, e in enumerate(locks):
            iid = f"L{e.uid}"
            seen.add(iid)
            state = e.last_error or ("" if e.enabled else "已停用")
            tags = ("bad",) if e.last_error else (("odd",) if i % 2 else ())
            values = ("●" if e.enabled else "○", e.label, e.vtype.label,
                      f"{e.target.describe()}", fmt_value(e.vtype, e.value),
                      str(e.writes), state)
            if iid in self.lock_rows:
                self.tree.item(iid, values=values, tags=tags)
            else:
                self.tree.insert("", "end", iid=iid, values=values, tags=tags)
                self.lock_rows[iid] = e.uid
        for iid in list(self.lock_rows):
            if iid not in seen:
                self.tree.delete(iid)
                self.lock_rows.pop(iid, None)

        seen = set()
        for i, e in enumerate(mons):
            iid = f"M{e.uid}"
            seen.add(iid)
            values = (e.label, e.vtype.label, e.target.describe(),
                      fmt_value(e.vtype, e.value), fmt_value(e.vtype, e.prev), "")
            if iid in self.mon_rows:
                self.mtree.item(iid, values=values)
            else:
                self.mtree.insert("", "end", iid=iid, values=values,
                                  tags=("odd",) if i % 2 else ())
                self.mon_rows[iid] = e.uid
        for iid in list(self.mon_rows):
            if iid not in seen:
                self.mtree.delete(iid)
                self.mon_rows.pop(iid, None)

    # -------------------------------------------------- 锁定操作

    def _selected_lock(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.app.freezer.get_lock(self.lock_rows[sel[0]])

    def new_lock(self) -> None:
        from .dialogs import LockDialog
        dlg = LockDialog(self, self.app, "新建锁定项")
        self.wait_window(dlg)
        if dlg.result:
            self.app.log(f"已新建锁定项：{dlg.result.label}  {dlg.result.target.describe()}")
            self.refresh()

    def edit_value(self) -> None:
        e = self._selected_lock()
        if not e:
            self.app.log("请先选中一个锁定项", "warn")
            return
        from .widgets import ask_values
        ok, raw, _ = ask_values(self, "修改锁定值", f"「{e.label}」锁定为：",
                                str(int(e.value) if float(e.value).is_integer() else e.value),
                                palette=self.app.palette)
        if not ok:
            return
        try:
            value = parse_value(raw, e.vtype)
        except ValueError as exc:
            self.app.log(str(exc), "err")
            return
        self.app.freezer.set_lock_value(e.uid, value)
        self.app.log(f"「{e.label}」锁定值已改为 {raw}")
        self.refresh()

    def toggle_enabled(self) -> None:
        e = self._selected_lock()
        if not e:
            return
        self.app.freezer.set_lock_enabled(e.uid, not e.enabled)
        self.app.log(f"「{e.label}」已{'启用' if not e.enabled else '停用'}")
        self.refresh()

    def remove_lock(self) -> None:
        e = self._selected_lock()
        if not e:
            return
        self.app.freezer.remove_lock(e.uid)
        self.app.log(f"已删除锁定项「{e.label}」")
        self.refresh()

    def disable_all(self) -> None:
        for e in self.app.freezer.locks.values():
            self.app.freezer.set_lock_enabled(e.uid, False)
        self.app.log("已停用全部锁定项")
        self.refresh()

    # -------------------------------------------------- 监视操作

    def _selected_monitor(self):
        sel = self.mtree.selection()
        if not sel:
            return None
        uid = self.mon_rows[sel[0]]
        return self.app.freezer.monitors.get(uid)

    def new_monitor(self) -> None:
        from .dialogs import LockDialog
        dlg = LockDialog(self, self.app, "新建监视项", monitor_mode=True)
        self.wait_window(dlg)
        if dlg.result:
            self.app.log(f"已新建监视项：{dlg.result.label}  {dlg.result.target.describe()}")
            self.refresh()

    def monitor_to_lock(self) -> None:
        m = self._selected_monitor()
        if not m:
            self.app.log("请先选中一个监视项", "warn")
            return
        self.app.freezer.add_lock(m.label, m.target, m.vtype,
                                  m.value if m.value is not None else 0)
        self.app.log(f"已把监视项「{m.label}」转为锁定项")
        self.refresh()

    def remove_monitor(self) -> None:
        m = self._selected_monitor()
        if not m:
            return
        self.app.freezer.remove_monitor(m.uid)
        self.refresh()

    def clear_monitors(self) -> None:
        for uid in list(self.app.freezer.monitors):
            self.app.freezer.remove_monitor(uid)
        self.refresh()
