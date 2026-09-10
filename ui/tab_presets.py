# -*- coding: utf-8 -*-
"""预设页：把定位好的地址保存下来，一键套用；槽位可被全局热键驱动。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core import presets as pr
from core.freezer import Target
from core.scanner import VALUE_TYPES

from .dialogs import PresetDialog
from .scaling import px, pxs
from .widgets import ask_values, attach_scroll, card, make_tree, tag_rows


class PresetsTab(ttk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app, padding=px(10))
        self.app = app
        self.rows: dict[str, dict] = {}
        self._build()
        self.refresh()

    def _build(self) -> None:
        top, body = card(
            self,
            "预设 = 已定位好的地址 + 类型 + 锁定值。绑定「功能槽位」后即可用全局热键一键开关。")

        wrap = ttk.Frame(body, style="Card.TFrame")
        wrap.pack(fill="both", expand=True)
        self.tree = make_tree(wrap, [
            ("name", "名称", 180), ("slot", "功能槽位", 140), ("type", "类型", 110),
            ("target", "地址 / 来源", 260), ("value", "锁定值", 110),
            ("lock", "默认锁定", 90), ("note", "备注", 160),
        ], height=12)
        self.tree.pack(side="left", fill="both", expand=True)
        attach_scroll(self.tree, wrap).pack(side="right", fill="y")
        tag_rows(self.tree, self.app.palette)
        self.tree.bind("<Double-1>", lambda _e: self.edit())

        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill="x", pady=pxs(8, 0))
        for text, cmd in [
            ("套用选中", self.apply_selected),
            ("套用全部", self.apply_all),
            ("从锁定项新建…", self.from_lock),
            ("用扫描选中地址新建…", self.from_scan),
            ("重新定位（用锁定项地址覆盖）", self.relocate),
            ("编辑…", self.edit),
            ("删除", self.delete),
        ]:
            ttk.Button(btns, text=text, command=cmd).pack(side="left", padx=pxs(0, 6))

        ttk.Separator(self).pack(fill="x", pady=px(10))
        hint, hbody = card(self, "槽位与热键对照")
        hint.pack(fill="x")
        grid = ttk.Frame(hbody, style="Card.TFrame")
        grid.pack(fill="x")
        mapping = self.app.cfg.get("hotkeys", {})
        for i, (slot, label) in enumerate(pr.ACTION_LABELS.items()):
            ttk.Label(grid, text=f"{mapping.get(slot, '未设置'):<16}",
                      style="Card.TLabel", font=("Consolas", 10, "bold")).grid(
                row=i // 2, column=(i % 2) * 2, sticky="w", padx=pxs(0, 6))
            ttk.Label(grid, text=f"{label}（槽位 {slot}）", style="DimCard.TLabel").grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=pxs(0, 24))

    # -------------------------------------------------- 数据

    def presets(self) -> list[dict]:
        return self.app.cfg.setdefault("presets", [])

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        for i, p in enumerate(self.presets()):
            iid = f"P{i}"
            target = Target.from_dict(p.get("target", {}))
            vt = pr.vtype_of(p)
            iid = self.tree.insert("", "end", iid=iid, values=(
                p.get("name", ""), p.get("slot", "") or "—", vt.label,
                target.describe(), p.get("value", 0),
                "是" if p.get("lock") else "否", p.get("note", ""),
            ), tags=("odd",) if i % 2 else ())
            self.rows[iid] = p

    def _selected(self) -> dict | None:
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def _store(self, new_list: list[dict]) -> None:
        self.app.cfg["presets"] = new_list
        self.app.save_cfg()
        self.refresh()

    # -------------------------------------------------- 操作

    def apply_selected(self) -> None:
        p = self._selected()
        if not p:
            self.app.log("请先选中一个预设", "warn")
            return
        entry = pr.apply_preset(p, self.app.freezer)
        self.app.log(f"已套用预设「{p['name']}」→ {entry.target.describe()}")
        self.app.goto_tab("locked")

    def apply_all(self) -> None:
        n = 0
        for p in self.presets():
            pr.apply_preset(p, self.app.freezer)
            n += 1
        self.app.log(f"已套用全部 {n} 个预设")
        self.app.goto_tab("locked")

    def from_lock(self) -> None:
        locks, _ = self.app.freezer.snapshot()
        if not locks:
            self.app.log("锁定表是空的，先扫描并锁定一个地址吧", "warn")
            return
        names = [f"{e.label}  ({e.target.describe()})" for e in locks]
        dlg = _Chooser(self, self.app, "选择要保存为预设的锁定项", names)
        self.wait_window(dlg)
        if dlg.index is None:
            return
        e = locks[dlg.index]
        preset = pr.make_preset(e.label, e.target, e.vtype, e.value,
                                lock=e.enabled, slot=e.slot, note="来自锁定项")
        self._store(pr.replace_or_add(self.presets(), preset))
        self.app.log(f"已生成预设「{preset['name']}」{preset['target']['kind']}")

    def from_scan(self) -> None:
        scan = self.app.scan_tab
        addrs = scan._selected_addrs() if scan else []
        if not addrs or not self.app.scanner:
            self.app.log("请先在「扫描」页选中一行地址", "warn")
            return
        vt = self.app.scanner.vt
        addr = addrs[0]
        ok, name, _ = ask_values(self, "新建预设", "预设名称：", f"新预设 {addr:#x}",
                                 palette=self.app.palette)
        if not ok or not name.strip():
            return
        value = self.app.scanner.read_one(addr)
        preset = pr.make_preset(name.strip(), Target(kind="direct", addr=addr), vt,
                                value if value is not None else 0, note="来自扫描")
        self._store(pr.replace_or_add(self.presets(), preset))
        self.app.log(f"已生成预设「{name.strip()}」（直接地址，重启游戏后可能失效）")

    def relocate(self) -> None:
        p = self._selected()
        if not p:
            return
        locks, _ = self.app.freezer.snapshot()
        if not locks:
            self.app.log("锁定表为空，无法覆盖地址", "warn")
            return
        e = locks[0]
        p["target"] = e.target.to_dict()
        p["type"] = e.vtype.key
        self._store(self.presets())
        self.app.log(f"预设「{p['name']}」的地址已更新为 {e.target.describe()}")

    def edit(self) -> None:
        p = self._selected()
        if not p:
            return
        dlg = PresetDialog(self, self.app, p)
        self.wait_window(dlg)
        if dlg.ok:
            self._store(pr.replace_or_add(self.presets(), dlg.preset))
            self.app.log(f"预设「{dlg.preset['name']}」已保存")

    def delete(self) -> None:
        p = self._selected()
        if not p:
            return
        self._store(pr.remove(self.presets(), p.get("name", "")))
        self.app.log(f"已删除预设「{p.get('name','')}」")


class _Chooser(tk.Toplevel):
    """简单的单选列表对话框。"""

    def __init__(self, parent, app, title: str, items: list[str]) -> None:
        super().__init__(parent)
        self.index: int | None = None
        self.transient(parent)
        self.title(title)
        self.configure(bg=app.palette["bg"])
        body = ttk.Frame(self, padding=px(14))
        body.pack(fill="both", expand=True)
        self.lb = tk.Listbox(body, height=min(14, max(4, len(items))), width=66,
                             activestyle="none",
                             bg=app.palette["entry_bg"], fg=app.palette["fg"],
                             selectbackground=app.palette["sel"],
                             highlightthickness=1,
                             highlightbackground=app.palette["border"],
                             font=("Microsoft YaHei UI", 10))
        for it in items:
            self.lb.insert("end", it)
        self.lb.pack(fill="both", expand=True)
        if items:
            self.lb.selection_set(0)
        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=pxs(10, 0))
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=pxs(8, 0))
        ttk.Button(btns, text="确定", style="Accent.TButton",
                   command=self._ok).pack(side="right")
        self.lb.bind("<Double-1>", lambda _e: self._ok())
        self.grab_set()

    def _ok(self) -> None:
        sel = self.lb.curselection()
        self.index = int(sel[0]) if sel else None
        self.destroy()
