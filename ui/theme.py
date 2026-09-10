# -*- coding: utf-8 -*-
"""界面主题：深色 / 浅色两套配色，统一 ttk 样式。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .scaling import px, pxs

FONT = "Microsoft YaHei UI"
MONO = "Consolas"

PALETTES = {
    "dark": {
        "bg": "#16181d",
        "panel": "#1e2128",
        "panel2": "#252932",
        "fg": "#e8eaf0",
        "fg_dim": "#98a0b0",
        "border": "#333947",
        "accent": "#7c5cff",
        "accent_fg": "#ffffff",
        "ok": "#3ecf8e",
        "warn": "#ffb454",
        "err": "#ff5d6c",
        "entry_bg": "#12141a",
        "tree_bg": "#1a1d24",
        "tree_alt": "#1f232b",
        "sel": "#3a3358",
        "head": "#272c37",
    },
    "light": {
        "bg": "#f4f5f8",
        "panel": "#ffffff",
        "panel2": "#eceef3",
        "fg": "#1b1e24",
        "fg_dim": "#5f6775",
        "border": "#ccd1da",
        "accent": "#6b4cff",
        "accent_fg": "#ffffff",
        "ok": "#0f9d63",
        "warn": "#b87100",
        "err": "#cf2f3d",
        "entry_bg": "#ffffff",
        "tree_bg": "#ffffff",
        "tree_alt": "#f3f5f9",
        "sel": "#dcd6ff",
        "head": "#e6e9f0",
    },
}


def palette(name: str) -> dict:
    return PALETTES.get(name, PALETTES["dark"])


def apply(root: tk.Misc, name: str) -> dict:
    p = palette(name)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=p["bg"])

    style.configure(".", background=p["bg"], foreground=p["fg"],
                    fieldbackground=p["entry_bg"], font=(FONT, 10))
    style.configure("TFrame", background=p["bg"])
    style.configure("Card.TFrame", background=p["panel"])
    style.configure("Bar.TFrame", background=p["panel2"])
    style.configure("TLabel", background=p["bg"], foreground=p["fg"])
    style.configure("Card.TLabel", background=p["panel"], foreground=p["fg"])
    style.configure("Dim.TLabel", background=p["bg"], foreground=p["fg_dim"])
    style.configure("DimCard.TLabel", background=p["panel"], foreground=p["fg_dim"])
    style.configure("Title.TLabel", background=p["bg"], foreground=p["fg"],
                    font=(FONT, 15, "bold"))
    style.configure("Sub.TLabel", background=p["bg"], foreground=p["fg_dim"],
                    font=(FONT, 9))
    style.configure("Mono.TLabel", background=p["panel"], foreground=p["fg"],
                    font=(MONO, 10))
    style.configure("Ok.TLabel", background=p["panel"], foreground=p["ok"])
    style.configure("Err.TLabel", background=p["panel"], foreground=p["err"])
    style.configure("Warn.TLabel", background=p["panel"], foreground=p["warn"])

    style.configure("TButton", background=p["panel2"], foreground=p["fg"],
                    bordercolor=p["border"], focuscolor=p["accent"],
                    relief="flat", padding=pxs(10, 5))
    style.map("TButton",
              background=[("active", p["border"]), ("disabled", p["panel"])],
              foreground=[("disabled", p["fg_dim"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    relief="flat", padding=pxs(12, 6))
    style.map("Accent.TButton",
              background=[("active", p["accent"]), ("disabled", p["border"])],
              foreground=[("disabled", p["fg_dim"])])

    # ---------------- 大按钮（给「一键」页用，手指友好、一眼能看清状态） ----------------
    style.configure("Big.TButton", background=p["panel2"], foreground=p["fg"],
                    relief="flat", padding=pxs(18, 12), anchor="w",
                    font=(FONT, 11, "bold"))
    style.map("Big.TButton",
              background=[("active", p["border"]), ("disabled", p["panel"])],
              foreground=[("disabled", p["fg_dim"])])
    style.configure("BigOn.TButton", background=p["ok"], foreground="#ffffff",
                    relief="flat", padding=pxs(18, 12), anchor="w",
                    font=(FONT, 11, "bold"))
    style.map("BigOn.TButton", background=[("active", p["ok"])])
    style.configure("Go.TButton", background=p["accent"], foreground=p["accent_fg"],
                    relief="flat", padding=pxs(20, 13), font=(FONT, 12, "bold"))
    style.map("Go.TButton",
              background=[("active", p["accent"]), ("disabled", p["border"])],
              foreground=[("disabled", p["fg_dim"])])
    style.configure("GoAlt.TButton", background=p["panel2"], foreground=p["accent"],
                    relief="flat", padding=pxs(20, 13), font=(FONT, 12, "bold"),
                    bordercolor=p["accent"])
    style.map("GoAlt.TButton",
              background=[("active", p["border"]), ("disabled", p["panel"])],
              foreground=[("disabled", p["fg_dim"])])

    style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"])
    style.map("TCheckbutton", background=[("active", p["bg"])])
    style.configure("Card.TCheckbutton", background=p["panel"], foreground=p["fg"])
    style.map("Card.TCheckbutton", background=[("active", p["panel"])])
    style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"])

    style.configure("TEntry", fieldbackground=p["entry_bg"], foreground=p["fg"],
                    bordercolor=p["border"], insertcolor=p["fg"], padding=px(4))
    style.configure("TCombobox", fieldbackground=p["entry_bg"], foreground=p["fg"],
                    background=p["panel2"], arrowcolor=p["fg"], padding=px(3))
    style.map("TCombobox", fieldbackground=[("readonly", p["entry_bg"])],
              foreground=[("readonly", p["fg"])])

    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"],
                    tabmargins=pxs(6, 6, 6, 0))
    style.configure("TNotebook.Tab", background=p["panel2"], foreground=p["fg_dim"],
                    padding=pxs(16, 7), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", p["panel"]), ("active", p["border"])],
              foreground=[("selected", p["accent"])])

    style.configure("Treeview", background=p["tree_bg"], fieldbackground=p["tree_bg"],
                    foreground=p["fg"], bordercolor=p["border"], rowheight=px(23),
                    font=(FONT, 10))
    style.map("Treeview",
              background=[("selected", p["sel"])],
              foreground=[("selected", p["fg"])])
    style.configure("Treeview.Heading", background=p["head"], foreground=p["fg"],
                    relief="flat", font=(FONT, 10, "bold"), padding=px(5))
    style.map("Treeview.Heading", background=[("active", p["border"])])

    style.configure("TProgressbar", background=p["accent"], troughcolor=p["panel2"],
                    bordercolor=p["panel2"], lightcolor=p["accent"],
                    darkcolor=p["accent"])
    style.configure("TSeparator", background=p["border"])
    style.configure("TScrollbar", background=p["panel2"], troughcolor=p["bg"],
                    bordercolor=p["bg"], arrowcolor=p["fg_dim"])
    style.map("TScrollbar", background=[("active", p["border"])])

    return p
