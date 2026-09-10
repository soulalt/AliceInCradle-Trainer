# -*- coding: utf-8 -*-
"""调试开关页：图形化读写游戏自带的 _debug.txt（写入前自动备份）。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core.debug_flags import FLAG_INFO

from .scaling import px, pxs
from .widgets import card, scroll_area


class DebugTab(ttk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app, padding=px(10))
        self.app = app
        self.rows: dict[str, tuple] = {}
        self._build()
        self.refresh()

    def _build(self) -> None:
        info, ibody = card(self, "游戏自带调试开关")
        info.pack(fill="x")
        ttk.Label(
            ibody,
            text="这些是《爱丽丝的摇篮》官方预留的调试开关，写在 "
                 "AliceInCradle_Data\\StreamingAssets\\_debug.txt 里。\n"
                 "本工具只改动目标行的数字，其余内容（注释、顺序、换行）逐字节保留；"
                 "首次修改前会生成 _debug.txt.orig.bak，随时可一键还原。\n"
                 "修改后需要重启游戏才会生效。",
            style="DimCard.TLabel", justify="left",
        ).pack(anchor="w")

        quick, qbody = card(self, "一键组合")
        quick.pack(fill="x", pady=pxs(10, 0))
        for text, cmd in [
            ("开启免伤（nodamage）", lambda: self._quick({"nodamage": 1})),
            ("开启攻击超强（mighty）", lambda: self._quick({"mighty": 1})),
            ("解锁全部技能（allskill）", lambda: self._quick({"allskill": 1})),
            ("解锁相册（albumunlock）", lambda: self._quick({"albumunlock": 1})),
            ("解锁 F7 调试菜单", self._unlock_f7),
            ("全部关闭（恢复默认）", self._disable_all),
        ]:
            ttk.Button(qbody, text=text, command=cmd).pack(side="left", padx=pxs(0, 6))

        table, tbody = card(self, "全部开关")
        table.pack(fill="both", expand=True, pady=pxs(10, 0))
        # 开关有二十来个，窗口矮或被放大时会超出可视范围，这里做成可滚动
        self.area, grid = scroll_area(tbody, self.app.palette["panel"])
        self.area.pack(fill="both", expand=True)
        self.grid = grid

        foot, fbody = card(self, "")
        foot.pack(fill="x", pady=pxs(10, 0))
        self.lb_state = ttk.Label(fbody, text="", style="Card.TLabel")
        self.lb_state.pack(side="left")
        for text, cmd in [
            ("重新读取", self._reload),
            ("回滚到上次修改前", lambda: self._restore("rollback")),
            ("还原到最初版本", lambda: self._restore("orig")),
            ("查看与原始的差异", self._show_diff),
        ]:
            ttk.Button(fbody, text=text, command=cmd).pack(side="right", padx=pxs(6, 0))

    # -------------------------------------------------- 读取

    def refresh(self) -> None:
        for child in self.grid.winfo_children():
            child.destroy()
        self.rows.clear()

        if self.app.debug is None:
            self.lb_state.configure(text="未找到 _debug.txt —— 请先在顶部设置正确的游戏目录")
            return
        if not self.app.debug.exists():
            self.lb_state.configure(text=f"文件不存在：{self.app.debug.path}")
            return

        entries = self.app.debug.entries()
        for i, e in enumerate(entries):
            ttk.Label(self.grid, text=e.key, style="Card.TLabel",
                      font=("Consolas", 10, "bold"), width=16, anchor="w").grid(
                row=i, column=0, sticky="w", pady=px(2))
            var = tk.StringVar(value=str(e.value))
            cb = ttk.Combobox(self.grid, textvariable=var, width=6, state="readonly",
                              values=["0", "1"] if e.key not in ("_player",) else
                              [str(x) for x in range(0, 4)])
            cb.grid(row=i, column=1, sticky="w", padx=pxs(6, 14), pady=px(2))
            ttk.Label(self.grid, text=e.desc or "游戏内置开关", style="DimCard.TLabel",
                      wraplength=px(380), justify="left").grid(
                row=i, column=2, sticky="w", pady=px(2))
            self.rows[e.key] = (var, cb, e.value)

        ttk.Button(self.grid, text="保存开关修改", style="Accent.TButton",
                   command=self.save).grid(row=len(entries), column=0, columnspan=3,
                                           sticky="w", pady=pxs(12, 0))
        self.area.scroll_to_top()
        self._update_state()

    def _reload(self) -> None:
        if self.app.debug:
            self.app.debug.load()
        self.refresh()
        self.app.log("已重新读取 _debug.txt")

    def _update_state(self) -> None:
        df = self.app.debug
        if not df:
            return
        marks = []
        if df.orig_backup.exists():
            marks.append("已有原始备份")
        if df.rollback_backup.exists():
            marks.append("已有回滚备份")
        vals = df.values()
        on = [k for k, v in vals.items() if v and k not in ("DEBUG",)]
        self.lb_state.configure(
            text=f"当前为 1 的开关：{'、'.join(on) if on else '（全部关闭）'}"
                 + ("；" + "；".join(marks) if marks else ""))

    # -------------------------------------------------- 写入

    def save(self) -> None:
        df = self.app.debug
        if not df:
            self.app.log("未找到 _debug.txt", "err")
            return
        mapping = {}
        for key, (var, _cb, old) in self.rows.items():
            try:
                val = int(var.get())
            except ValueError:
                continue
            if val != old:
                mapping[key] = val
        if not mapping:
            self.app.log("没有需要保存的变更")
            return
        if df.set_many(mapping):
            detail = "、".join(f"{k}={v}" for k, v in mapping.items())
            self.app.log(f"_debug.txt 已更新：{detail}（重启游戏后生效）")
            self.refresh()
        else:
            self.app.log(f"写入失败：{df.last_error}", "err")

    def _quick(self, mapping: dict) -> None:
        df = self.app.debug
        if not df:
            self.app.log("未找到 _debug.txt", "err")
            return
        if df.set_many(mapping):
            self.app.log(f"已设置 " + "、".join(f"{k}={v}" for k, v in mapping.items())
                         + "（重启游戏后生效）")
            self.refresh()
        else:
            self.app.log(f"写入失败：{df.last_error}", "err")

    def _unlock_f7(self) -> None:
        df = self.app.debug
        if not df:
            self.app.log("未找到 _debug.txt", "err")
            return
        if df.unlock_f7_menu():
            self.app.log("已按游戏注释解锁 F7 调试菜单（announce=1 且 timestamp=1），"
                         "重启游戏后游戏中按 F7 试试")
            self.refresh()
        else:
            self.app.log(f"写入失败：{df.last_error}", "err")

    def _disable_all(self) -> None:
        df = self.app.debug
        if not df:
            return
        vals = df.values()
        mapping = {k: 0 for k in vals if k not in ("DEBUG", "benchmark") and vals[k] == 1}
        if "benchmark" in vals:
            mapping["benchmark"] = 1
        if not mapping:
            self.app.log("当前没有需要关闭的开关")
            return
        df.set_many(mapping)
        self.app.log("已把调试开关全部设为 0（DEBUG 总闸保留）")
        self.refresh()

    def _restore(self, source: str) -> None:
        from tkinter import messagebox
        df = self.app.debug
        if not df:
            return
        name = "最初版本" if source == "orig" else "上一次修改前"
        if not messagebox.askyesno(
                "确认还原",
                f"将把 _debug.txt 还原为「{name}」的内容。\n"
                f"当前文件会先另存为 .before_restore 以防万一。\n\n确定继续？",
                parent=self):
            return
        if df.restore(source):
            self.app.log(f"_debug.txt 已还原为{name}")
            self.refresh()
        else:
            self.app.log(f"还原失败：{df.last_error}", "err")

    def _show_diff(self) -> None:
        from tkinter import messagebox
        df = self.app.debug
        if not df:
            return
        diff = df.diff_summary()
        if not diff:
            messagebox.showinfo("差异", "与最初版本完全一致（或还没有原始备份）。", parent=self)
            return
        head = diff[:20]
        more = "" if len(diff) <= 20 else f"\n\n…共 {len(diff)} 处差异，仅显示前 20 处"
        messagebox.showinfo("与最初版本的差异", "\n\n".join(head) + more, parent=self)
