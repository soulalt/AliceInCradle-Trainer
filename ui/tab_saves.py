# -*- coding: utf-8 -*-
"""存档页：备份与还原 savedata / whole.data / config.cfg，操作全部可逆。"""

from __future__ import annotations

import os
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

from core import paths, saves

from .scaling import px, pxs
from .widgets import attach_scroll, card, make_tree, tag_rows


class SavesTab(ttk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app, padding=px(10))
        self.app = app
        self.rows: dict[str, object] = {}
        self._build()
        self.refresh()

    def _build(self) -> None:
        info, ibody = card(self, "存档位置")
        info.pack(fill="x")
        self.lb_dir = ttk.Label(ibody, text="", style="Card.TLabel", wraplength=px(760),
                                justify="left")
        self.lb_dir.pack(anchor="w")
        self.lb_files = ttk.Label(ibody, text="", style="DimCard.TLabel", wraplength=px(760),
                                  justify="left")
        self.lb_files.pack(anchor="w", pady=pxs(4, 0))
        self.v_auto = tk.BooleanVar(value=bool(self.app.cfg.get("autobackup_saves", True)))
        ttk.Checkbutton(ibody, text="附加游戏时自动备份一次存档（30 分钟内不重复）",
                        variable=self.v_auto, style="Card.TCheckbutton",
                        command=self._save_pref).pack(anchor="w", pady=pxs(6, 0))

        table, tbody = card(self, "备份历史")
        table.pack(fill="both", expand=True, pady=pxs(10, 0))
        wrap = ttk.Frame(tbody, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.tree = make_tree(wrap, [
            ("time", "备份时间", 170), ("tag", "标签", 120), ("count", "文件数", 70),
            ("size", "大小", 90), ("path", "目录", 320),
        ], height=12)
        self.tree.pack(side="left", fill="both", expand=True)
        attach_scroll(self.tree, wrap).pack(side="right", fill="y")
        tag_rows(self.tree, self.app.palette)

        btns = ttk.Frame(tbody, style="Card.TFrame")
        btns.pack(fill="x", pady=pxs(8, 0))
        for text, cmd in [
            ("立即备份", self.backup_now),
            ("还原选中…", self.restore),
            ("校验选中", self.verify),
            ("删除选中备份", self.delete),
            ("打开存档目录", lambda: self._open(paths.save_dir())),
            ("打开备份目录", lambda: self._open(paths.backup_dir())),
        ]:
            ttk.Button(btns, text=text, command=cmd).pack(side="left", padx=pxs(0, 6))

        self.lb_state = ttk.Label(tbody, text="", style="DimCard.TLabel")
        self.lb_state.pack(anchor="w", pady=pxs(6, 0))

    # -------------------------------------------------- 显示

    def refresh(self) -> None:
        sd = paths.save_dir()
        files = paths.save_files()
        self.lb_dir.configure(text=f"存档目录：{sd}")
        if files:
            detail = "、".join(
                f"{f.name}（{paths.human_size(f.stat().st_size)}，"
                f"{self._mtime(f)}）" for f in files)
            self.lb_files.configure(text="当前存档：" + detail)
        else:
            self.lb_files.configure(text="当前存档：未找到（也许还没创建过存档）")

        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        infos = saves.list_backups()
        for i, info in enumerate(infos):
            iid = f"B{i}"
            iid = self.tree.insert("", "end", iid=iid, values=(
                info.created, info.tag, len(info.files),
                paths.human_size(info.total_size), str(info.path),
            ), tags=("odd",) if i % 2 else ())
            self.rows[iid] = info
        self.lb_state.configure(
            text=f"共 {len(infos)} 个备份；还原前会自动再做一次 prerestore 安全备份。")

    @staticmethod
    def _mtime(p) -> str:
        import datetime
        try:
            return datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M")
        except OSError:
            return "?"

    def _save_pref(self) -> None:
        self.app.cfg["autobackup_saves"] = bool(self.v_auto.get())
        self.app.save_cfg()

    def _selected(self):
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    @staticmethod
    def _open(path) -> None:
        try:
            os.startfile(str(path))       # noqa: S606 - Windows 专用
        except Exception:
            subprocess.Popen(["explorer", str(path)])

    # -------------------------------------------------- 操作

    def backup_now(self) -> None:
        target, msg = saves.create_backup("manual")
        self.app.log(msg, "info" if target else "warn")
        self.refresh()

    def restore(self) -> None:
        info = self._selected()
        if not info:
            self.app.log("请先选中一个备份", "warn")
            return
        if not messagebox.askyesno(
                "确认还原存档",
                f"将用备份「{info.created}」覆盖当前存档：\n\n"
                + "\n".join("  • " + f.get("name", "?") for f in info.files)
                + "\n\n建议先关闭游戏再还原。当前存档会先自动备份一次。\n\n确定继续？",
                parent=self):
            return
        ok, msg = saves.restore_backup(info.path)
        self.app.log(msg, "info" if ok else "err")
        self.refresh()

    def verify(self) -> None:
        info = self._selected()
        if not info:
            return
        problems = saves.verify_backup(info.path)
        if problems:
            self.app.log("校验发现问题：" + "；".join(problems), "err")
        else:
            self.app.log(f"备份「{info.created}」校验通过，所有文件 sha256 一致")

    def delete(self) -> None:
        info = self._selected()
        if not info:
            return
        if not messagebox.askyesno("确认删除", f"删除备份目录？\n{info.path}", parent=self):
            return
        import shutil
        try:
            shutil.rmtree(info.path)
            self.app.log(f"已删除备份 {info.path.name}")
        except OSError as exc:
            self.app.log(f"删除失败：{exc}", "err")
        self.refresh()
