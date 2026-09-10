# -*- coding: utf-8 -*-
"""通用界面控件与工具：后台任务、数值输入对话框、卡片容器、地址格式化。"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from .scaling import px, pxs
from .theme import FONT, MONO


# ---------------------------------------------------------------- 格式化

def fmt_addr(addr: int) -> str:
    return f"0x{addr:012X}" if addr else "—"


def fmt_num(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if value != value:                       # NaN
            return "NaN"
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


# ---------------------------------------------------------------- 卡片容器

def card(parent, title: str = "", pad: int = 10) -> tuple[ttk.Frame, ttk.Frame]:
    """返回 (外框, 内容框)。title 非空时在内容框顶部放一行小标题。"""
    outer = ttk.Frame(parent, style="Card.TFrame", padding=px(pad))
    if title:
        ttk.Label(outer, text=title, style="Card.TLabel",
                  font=(FONT, 10, "bold")).pack(anchor="w", pady=pxs(0, 6))
    inner = ttk.Frame(outer, style="Card.TFrame")
    inner.pack(fill="both", expand=True)
    return outer, inner


def labeled(parent, text: str, style: str = "DimCard.TLabel") -> ttk.Label:
    return ttk.Label(parent, text=text, style=style)


# ---------------------------------------------------------------- 后台任务

class Task:
    """带进度与取消的后台任务句柄。"""

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def run_async(widget: tk.Misc,
              work,
              on_done=None,
              on_error=None,
              on_progress=None,
              delay: int = 50) -> Task:
    """在后台线程执行 work(progress, is_cancelled)，结果回主线程处理。

    progress(frac: float, text: str)  /  is_cancelled() -> bool
    """
    task = Task()
    q: "queue.Queue[tuple]" = queue.Queue()

    def progress(frac: float, text: str) -> None:
        q.put(("p", frac, text))

    def runner() -> None:
        try:
            result = work(progress, lambda: task.cancelled)
            q.put(("d", result, None))
        except Exception as exc:                 # noqa: BLE001 - 回传给 UI 展示
            q.put(("e", None, exc))

    threading.Thread(target=runner, name="task", daemon=True).start()

    def poll() -> None:
        try:
            while True:
                kind = q.get_nowait()
                if kind[0] == "p":
                    if on_progress:
                        on_progress(kind[1], kind[2])
                elif kind[0] == "d":
                    if on_done:
                        on_done(kind[1])
                    return
                else:
                    if on_error:
                        on_error(kind[2])
                    return
        except queue.Empty:
            pass
        widget.after(delay, poll)

    widget.after(delay, poll)
    return task


# ---------------------------------------------------------------- 数值输入对话框

class ValueDialog(tk.Toplevel):
    """要求用户输入一个数值（或 起始 / 结束 两个）。返回 (ok, v1, v2)。"""

    def __init__(self, parent, title: str, prompt: str, initial: str = "",
                 second: bool = False, second_prompt: str = "结束值",
                 initial2: str = "", palette: dict | None = None) -> None:
        super().__init__(parent)
        self.result: tuple[bool, str, str] = (False, "", "")
        self.transient(parent)
        self.title(title)
        self.resizable(False, False)
        p = palette or {}
        self.configure(bg=p.get("bg", "#16181d"))

        body = ttk.Frame(self, padding=px(16))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=prompt).grid(row=0, column=0, sticky="w", pady=pxs(0, 6))
        self.e1 = ttk.Entry(body, width=26)
        self.e1.grid(row=0, column=1, sticky="ew", padx=pxs(10, 0), pady=pxs(0, 6))
        self.e1.insert(0, initial)
        row = 1
        if second:
            ttk.Label(body, text=second_prompt).grid(row=1, column=0, sticky="w",
                                                     pady=pxs(0, 6))
            self.e2 = ttk.Entry(body, width=26)
            self.e2.grid(row=1, column=1, sticky="ew", padx=pxs(10, 0), pady=pxs(0, 6))
            self.e2.insert(0, initial2)
            row = 2

        btns = ttk.Frame(body)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=pxs(12, 0))
        ttk.Button(btns, text="取消", command=self._cancel).pack(side="right", padx=pxs(8, 0))
        ttk.Button(btns, text="确定", style="Accent.TButton",
                   command=self._ok).pack(side="right")

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.grab_set()
        self.e1.focus_set()
        self.e1.select_range(0, "end")

    def _ok(self) -> None:
        v1 = self.e1.get().strip()
        v2 = self.e2.get().strip() if hasattr(self, "e2") else ""
        self.result = (True, v1, v2)
        self.destroy()

    def _cancel(self) -> None:
        self.result = (False, "", "")
        self.destroy()


def ask_values(parent, title: str, prompt: str, initial: str = "",
               second: bool = False, second_prompt: str = "结束值",
               initial2: str = "", palette: dict | None = None) -> tuple[bool, str, str]:
    parent.update_idletasks()
    dlg = ValueDialog(parent, title, prompt, initial, second, second_prompt,
                      initial2, palette)
    parent.wait_window(dlg)
    return dlg.result


# ---------------------------------------------------------------- 表格助手

def make_tree(parent, columns: list[tuple[str, str, int]], height: int = 12,
              select: str = "extended") -> ttk.Treeview:
    """columns: [(列标识, 表头, 宽度), ...]。宽度按当前缩放换算。"""
    tree = ttk.Treeview(parent, columns=[c[0] for c in columns],
                        show="headings", height=height, selectmode=select)
    for key, head, width in columns:
        tree.heading(key, text=head)
        tree.column(key, width=px(width), anchor="w", stretch=(key == columns[-1][0]))
    return tree


def attach_scroll(tree: ttk.Treeview, parent) -> ttk.Scrollbar:
    sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    return sb


_SCROLL_AREAS: list["ScrollArea"] = []


def _dispatch_wheel(event) -> None:
    """全局滚轮分发：谁的范围内谁滚。

    不用 Enter/Leave 接管绑定 —— 那样鼠标移到区域内的子控件（卡片、下拉框）上时
    会触发 Leave，滚轮就失效了。改成全局只绑一次，按指针位置逐个判断归属。
    """
    for area in list(_SCROLL_AREAS):
        if area.owns(event.widget):
            area.scroll_by(event)
            return


class ScrollArea(ttk.Frame):
    """把任意内容包成可纵向滚动的区域。

    用于内容高度会超出窗口的页面（如「一键」页、「调试开关」页）：
    窗口矮或被缩放放大时，内容不会凭空被裁掉，而是出现滚动条。
    """

    def __init__(self, parent, bg: str, style: str = "Card.TFrame") -> None:
        super().__init__(parent, style=style)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bg)
        self.vs = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vs.set)
        self.vs.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas, style=style)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)

        _SCROLL_AREAS.append(self)
        if len(_SCROLL_AREAS) == 1:
            self.canvas.bind_all("<MouseWheel>", _dispatch_wheel)

    # -------------------------------------------------- 内部

    def owns(self, widget) -> bool:
        """指针所在控件是不是属于本区域（含区域内的子控件）。"""
        node = widget
        while node is not None:
            if node is self:
                return True
            node = getattr(node, "master", None)
        return False

    def scroll_by(self, event) -> None:
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return                       # 内容没超高，不必滚动
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_inner(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        # 内框宽度跟随画布，内容才能正确换行
        self.canvas.itemconfigure(self._win, width=event.width)

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0.0)


def scroll_area(parent, bg: str, style: str = "Card.TFrame"
                ) -> tuple["ScrollArea", ttk.Frame]:
    """便捷构造：返回 (滚动容器, 用于放内容的内部 Frame)。"""
    area = ScrollArea(parent, bg, style)
    return area, area.inner


def tag_rows(tree: ttk.Treeview, palette: dict) -> None:
    tree.tag_configure("odd", background=palette.get("tree_alt"))
    tree.tag_configure("hit", foreground=palette.get("ok"))
    tree.tag_configure("bad", foreground=palette.get("err"))
    tree.tag_configure("warn", foreground=palette.get("warn"))
