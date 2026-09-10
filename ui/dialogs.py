# -*- coding: utf-8 -*-
"""对话框：新建锁定/监视项、编辑预设。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core.freezer import parse_target
from core.presets import ACTION_LABELS
from core.scanner import TYPE_ORDER, VALUE_TYPES, parse_value

from .scaling import px, pxs
from .widgets import fmt_addr


class LockDialog(tk.Toplevel):
    def __init__(self, parent, app, title: str, monitor_mode: bool = False) -> None:
        super().__init__(parent)
        self.app = app
        self.monitor_mode = monitor_mode
        self.result = None

        self.transient(parent)
        self.title(title)
        self.resizable(False, False)
        self.configure(bg=app.palette["bg"])
        body = ttk.Frame(self, padding=px(16))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(body, text="名称").grid(row=r, column=0, sticky="w", pady=px(4))
        self.e_name = ttk.Entry(body, width=34)
        self.e_name.grid(row=r, column=1, sticky="ew", padx=pxs(10, 0), pady=px(4))
        self.e_name.insert(0, "监视项" if monitor_mode else "新锁定项")
        r += 1

        ttk.Label(body, text="地址表达式").grid(row=r, column=0, sticky="w", pady=px(4))
        self.e_addr = ttk.Entry(body, width=34)
        self.e_addr.grid(row=r, column=1, sticky="ew", padx=pxs(10, 0), pady=px(4))
        if app.scanner and app.scanner.count:
            self.e_addr.insert(0, fmt_addr(app.scanner.addrs[0]))
        r += 1

        ttk.Label(body, text="示例：0x1F3A2B40 或 AliceInCradle.exe+0x10+0x28",
                  style="Dim.TLabel").grid(row=r, column=0, columnspan=2, sticky="w", pady=pxs(0, 6))
        r += 1

        ttk.Label(body, text="数值类型").grid(row=r, column=0, sticky="w", pady=px(4))
        self.cb_type = ttk.Combobox(body, width=32, state="readonly",
                                    values=[VALUE_TYPES[k].label for k in TYPE_ORDER])
        default = "4bytes"
        if app.scanner:
            default = app.scanner.vt.key
        self.cb_type.current(TYPE_ORDER.index(default))
        self.cb_type.grid(row=r, column=1, sticky="w", padx=pxs(10, 0), pady=px(4))
        r += 1

        if not monitor_mode:
            ttk.Label(body, text="锁定值").grid(row=r, column=0, sticky="w", pady=px(4))
            self.e_value = ttk.Entry(body, width=34)
            self.e_value.grid(row=r, column=1, sticky="ew", padx=pxs(10, 0), pady=px(4))
            r += 1

            ttk.Label(body, text="功能槽位（可选）").grid(row=r, column=0, sticky="w", pady=px(4))
            slots = ["（不绑定）"] + [f"{k} —— {v}" for k, v in ACTION_LABELS.items()]
            self.cb_slot = ttk.Combobox(body, width=32, state="readonly", values=slots)
            self.cb_slot.current(0)
            self.cb_slot.grid(row=r, column=1, sticky="w", padx=pxs(10, 0), pady=px(4))
            r += 1
            ttk.Label(body, text="绑定槽位后可用全局热键开关它", style="Dim.TLabel").grid(
                row=r, column=0, columnspan=2, sticky="w", pady=pxs(0, 6))
            r += 1

        # 已加载模块提示
        if app.proc and app.proc.opened:
            mods = [m.name for m in app.proc.modules()][:12]
            ttk.Label(body, text="已加载模块：" + "、".join(mods),
                      style="Dim.TLabel", wraplength=px(420)).grid(
                row=r, column=0, columnspan=2, sticky="w", pady=pxs(4, 0))
            r += 1

        btns = ttk.Frame(body)
        btns.grid(row=r, column=0, columnspan=2, sticky="e", pady=pxs(14, 0))
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=pxs(8, 0))
        ttk.Button(btns, text="确定", style="Accent.TButton",
                   command=self._ok).pack(side="right")

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.e_name.focus_set()

    def _ok(self) -> None:
        app = self.app
        name = self.e_name.get().strip() or "未命名"
        try:
            target = parse_target(self.e_addr.get())
        except ValueError as exc:
            app.log(str(exc), "err")
            return
        vtype = VALUE_TYPES[TYPE_ORDER[self.cb_type.current()]]

        if self.monitor_mode:
            self.result = app.freezer.add_monitor(name, target, vtype)
        else:
            try:
                value = parse_value(self.e_value.get(), vtype)
            except ValueError as exc:
                app.log(str(exc), "err")
                return
            slot = ""
            idx = self.cb_slot.current()
            if idx > 0:
                slot = list(ACTION_LABELS)[idx - 1]
            self.result = app.freezer.add_lock(name, target, vtype, value, slot=slot)
        self.destroy()


class PresetDialog(tk.Toplevel):
    """编辑预设的名称 / 槽位 / 值。"""

    def __init__(self, parent, app, preset: dict) -> None:
        super().__init__(parent)
        self.preset = dict(preset)
        self.ok = False
        self.transient(parent)
        self.title("编辑预设")
        self.resizable(False, False)
        self.configure(bg=app.palette["bg"])
        body = ttk.Frame(self, padding=px(16))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="名称").grid(row=0, column=0, sticky="w", pady=px(4))
        self.e_name = ttk.Entry(body, width=32)
        self.e_name.grid(row=0, column=1, sticky="ew", padx=pxs(10, 0), pady=px(4))
        self.e_name.insert(0, preset.get("name", ""))

        ttk.Label(body, text="功能槽位").grid(row=1, column=0, sticky="w", pady=px(4))
        slots = ["（不绑定）"] + [f"{k} —— {v}" for k, v in ACTION_LABELS.items()]
        self.cb_slot = ttk.Combobox(body, width=30, state="readonly", values=slots)
        keys = list(ACTION_LABELS)
        cur = preset.get("slot", "")
        self.cb_slot.current(keys.index(cur) + 1 if cur in keys else 0)
        self.cb_slot.grid(row=1, column=1, sticky="w", padx=pxs(10, 0), pady=px(4))

        ttk.Label(body, text="锁定值").grid(row=2, column=0, sticky="w", pady=px(4))
        self.e_value = ttk.Entry(body, width=32)
        self.e_value.grid(row=2, column=1, sticky="ew", padx=pxs(10, 0), pady=px(4))
        self.e_value.insert(0, str(preset.get("value", 0)))

        ttk.Label(body, text="地址").grid(row=3, column=0, sticky="w", pady=px(4))
        from core.freezer import Target
        ttk.Label(body, text=Target.from_dict(preset.get("target", {})).describe(),
                  style="Dim.TLabel").grid(row=3, column=1, sticky="w", padx=pxs(10, 0), pady=px(4))

        btns = ttk.Frame(body)
        btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=pxs(14, 0))
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=pxs(8, 0))
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right")
        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _save(self) -> None:
        self.preset["name"] = self.e_name.get().strip() or "未命名"
        keys = list(ACTION_LABELS)
        idx = self.cb_slot.current()
        self.preset["slot"] = keys[idx - 1] if idx > 0 else ""
        try:
            self.preset["value"] = float(self.e_value.get().strip() or 0)
        except ValueError:
            pass
        self.ok = True
        self.destroy()
