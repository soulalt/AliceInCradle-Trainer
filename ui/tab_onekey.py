# -*- coding: utf-8 -*-
"""「一键」页：不想研究扫描原理的人，只看这一页就够了。

刻意排成四步，顺序就是该做的事：
    ① 连上游戏
    ② 点想要的开关（游戏自带，零风险）
    ③ 金币 / 物品数量这类数值 —— 跟着提示点几下就找出来了
    ④ 改坏了怎么一键还原

所有专业术语（字节宽度、筛选模式、地址、指针）都留在这页之外；
页面上出现的每个按钮，都写着「点了会发生什么」。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import presets as pr
from core.autofind import DONE_THRESHOLD, PURPOSES, Wizard
from core.freezer import Target
from core.scanner import fmt_value

from .scaling import px, pxs
from .widgets import card, fmt_addr, make_tree, run_async, scroll_area, tag_rows

# 这一页只放最常用的几个开关，其余在「调试开关」页
QUICK_FLAGS: list[tuple[str, str]] = [
    ("nodamage", "免伤 —— 受到的伤害变成 0"),
    ("mighty", "攻击超强 —— 一下就秒掉小怪"),
    ("allskill", "解锁全部隐藏技能"),
    ("albumunlock", "解锁相册里的全部内容"),
]
F7_KEY = "__f7__"
F7_LABEL = "解锁游戏内调试菜单（游戏里按 F7 打开）"

ON, OFF = "● 已开启", "○ 未开启"


class OneKeyTab(ttk.Frame):
    def __init__(self, app) -> None:
        super().__init__(app, padding=px(10))
        self.app = app
        self.wizard: Wizard | None = None
        self._flag_buttons: dict[str, ttk.Button] = {}
        self._busy = False
        self._build()
        self._on_purpose()
        self.refresh()

    # ================================================== 构建

    def _build(self) -> None:
        # 这一页内容多（四步），窗口矮或缩放放大时会超出可视高度，所以整页可滚动
        self.area, page = scroll_area(self, self.app.palette["bg"], style="TFrame")
        self.area.pack(fill="both", expand=True)

        # ---------------- ① 连上游戏 ----------------
        s1, b1 = card(page, "第 1 步　连上游戏")
        s1.pack(fill="x")
        row = ttk.Frame(b1, style="Card.TFrame")
        row.pack(fill="x")
        self.btn_connect = ttk.Button(row, text="启动游戏并连接", style="Go.TButton",
                                      command=self._connect)
        self.btn_connect.pack(side="left")
        ttk.Button(row, text="我已经开了游戏，直接连接", style="GoAlt.TButton",
                   command=self._attach_existing).pack(side="left", padx=pxs(10, 0))
        self.lb_conn = ttk.Label(b1, text="", style="DimCard.TLabel")
        self.lb_conn.pack(anchor="w", pady=pxs(8, 0))
        self.v_auto = tk.BooleanVar(value=bool(self.app.cfg.get("auto_attach", True)))
        ttk.Checkbutton(b1, text="游戏启动后自动连接（不用再点按钮）", variable=self.v_auto,
                        style="Card.TCheckbutton",
                        command=self._save_auto).pack(anchor="w", pady=pxs(4, 0))

        # ---------------- ② 游戏自带开关 ----------------
        s2, b2 = card(page, "第 2 步　想要什么效果？点一下就开（游戏自带开关，不会把游戏改坏）")
        s2.pack(fill="x", pady=pxs(10, 0))
        ttk.Label(b2, text="这几项是游戏官方预留的调试开关，工具只改开关数值，不碰游戏程序本身。"
                           "开关状态会记在游戏里，重开游戏依然有效。",
                  style="DimCard.TLabel", wraplength=px(900),
                  justify="left").pack(anchor="w", pady=pxs(0, 8))
        self.flag_box = ttk.Frame(b2, style="Card.TFrame")
        self.flag_box.pack(fill="x")
        self.btn_all_off = ttk.Button(b2, text="全部关掉，恢复原样",
                                      command=self._all_flags_off)
        self.btn_all_off.pack(anchor="w", pady=pxs(10, 0))
        self.lb_flag_note = ttk.Label(b2, text="", style="Warn.TLabel")
        self.lb_flag_note.pack(anchor="w", pady=pxs(6, 0))
        ttk.Label(b2, text="↓ 窗口不够高时，本页可以往下滚：下面还有"
                           "「第 3 步 改金币 / 物品数量」和「第 4 步 一键还原」",
                  style="DimCard.TLabel").pack(anchor="w", pady=pxs(8, 0))

        # ---------------- ③ 找数值 ----------------
        s3, b3 = card(page, "第 3 步　金币、物品数量这类数值 —— 跟着提示点几下就行")
        s3.pack(fill="x", pady=pxs(10, 0))

        pick = ttk.Frame(b3, style="Card.TFrame")
        pick.pack(fill="x")
        ttk.Label(pick, text="要找什么？", style="Card.TLabel").pack(side="left")
        self.cb_purpose = ttk.Combobox(pick, width=18, state="readonly",
                                       values=[p.label for p in PURPOSES.values()])
        self.cb_purpose.current(0)
        self.cb_purpose.pack(side="left", padx=pxs(8, 0))
        self.cb_purpose.bind("<<ComboboxSelected>>", lambda _e: self._on_purpose())
        self.lb_ask = ttk.Label(pick, text="", style="Card.TLabel")
        self.lb_ask.pack(side="left", padx=pxs(16, 0))
        self.e_value = ttk.Entry(pick, width=14)
        self.e_value.pack(side="left")
        self.e_value.bind("<Return>", lambda _e: self._begin())
        self.btn_begin = ttk.Button(pick, text="开始找", style="Accent.TButton",
                                    command=self._begin)
        self.btn_begin.pack(side="left", padx=pxs(8, 0))
        ttk.Button(pick, text="重新开始", command=self._reset).pack(side="left")

        # 两条大按钮：用户按的按钮上写的就是他刚做过的事，不用理解"筛选模式"
        step = ttk.Frame(b3, style="Card.TFrame")
        step.pack(fill="x", pady=pxs(12, 0))
        self.btn_smaller = ttk.Button(step, text="我在游戏里把它【变小】了 → 再缩小范围",
                                      style="Go.TButton", state="disabled",
                                      command=lambda: self._narrow(False))
        self.btn_smaller.pack(side="left")
        self.btn_bigger = ttk.Button(step, text="我在游戏里把它【变大】了 → 再缩小范围",
                                     style="GoAlt.TButton", state="disabled",
                                     command=lambda: self._narrow(True))
        self.btn_bigger.pack(side="left", padx=pxs(10, 0))

        self.lb_state = ttk.Label(b3, text="", style="Card.TLabel", wraplength=px(980),
                                  justify="left")
        self.lb_state.pack(anchor="w", pady=pxs(10, 0))
        self.lb_tip = ttk.Label(b3, text="", style="DimCard.TLabel", wraplength=px(980),
                                justify="left")
        self.lb_tip.pack(anchor="w")

        # 候选（收敛到很少时才有意义，多了不显示免得刷屏）
        wrap = ttk.Frame(b3, style="Card.TFrame")
        wrap.pack(fill="x", pady=pxs(10, 0))
        self.tree = make_tree(wrap, [("addr", "找到的位置", 220),
                                     ("value", "当前数值", 160)], height=5,
                              select="browse")
        self.tree.pack(side="left", fill="both", expand=True)
        tag_rows(self.tree, self.app.palette)

        apply_row = ttk.Frame(b3, style="Card.TFrame")
        apply_row.pack(fill="x", pady=pxs(6, 0))
        ttk.Label(apply_row, text="锁定为", style="Card.TLabel").pack(side="left")
        self.e_lock = ttk.Entry(apply_row, width=12)
        self.e_lock.pack(side="left", padx=pxs(6, 0))
        self.btn_lock = ttk.Button(apply_row, text="锁定它（数值就不掉/不花了）",
                                   style="Accent.TButton", state="disabled",
                                   command=self._lock)
        self.btn_lock.pack(side="left", padx=pxs(10, 0))
        self.btn_save = ttk.Button(apply_row, text="存为预设（以后一键套用）",
                                   state="disabled", command=self._save_preset)
        self.btn_save.pack(side="left")

        # ---------------- ④ 还原 ----------------
        s4, b4 = card(page, "万一改坏了　——　点这里全部还原")
        s4.pack(fill="x", pady=pxs(10, 0))
        row4 = ttk.Frame(b4, style="Card.TFrame")
        row4.pack(fill="x")
        for text, cmd in [
            ("停用全部锁定（游戏立即恢复正常）", self._disable_locks),
            ("把游戏开关全部关掉", self._all_flags_off),
            ("还原 _debug.txt 到最初的样子", self._restore_orig),
        ]:
            ttk.Button(row4, text=text, command=cmd).pack(side="left", padx=pxs(0, 8))
        ttk.Label(b4, text="还原不会删除你的存档；存档页还留着附加游戏时自动做的备份。",
                  style="DimCard.TLabel").pack(anchor="w", pady=pxs(8, 0))

    # ================================================== ① 连接

    def _connect(self) -> None:
        if self.app.proc and self.app.proc.opened:
            self.app.log("已经连上游戏了")
            return
        self.app.launch_and_attach()

    def _attach_existing(self) -> None:
        if not self.app.attach():
            messagebox.showinfo(
                "没找到游戏", "没有检测到正在运行的《爱丽丝的摇篮》。\n\n"
                              "请先双击游戏目录里的 AliceInCradle.exe 启动游戏，"
                              "再回到这里点「我已经开了游戏，直接连接」。", parent=self)

    def _save_auto(self) -> None:
        self.app.cfg["auto_attach"] = bool(self.v_auto.get())
        self.app.save_cfg()
        self.app.log("已开启「游戏启动后自动连接」" if self.v_auto.get()
                     else "已关闭「游戏启动后自动连接」")

    def refresh_connection(self) -> None:
        proc = self.app.proc
        if proc and proc.opened and proc.alive():
            self.lb_conn.configure(text=f"已经连上游戏了（进程号 {proc.pid}）——可以做下面的事",
                                   style="Ok.TLabel")
            self.btn_connect.configure(state="disabled")
        elif proc and proc.opened:
            self.lb_conn.configure(text="游戏已经退出了。关掉游戏后重开，再点上面按钮连接。",
                                   style="Warn.TLabel")
            self.btn_connect.configure(state="normal")
        else:
            self.lb_conn.configure(text="还没连上游戏：先启动游戏，再点左边的按钮。"
                                        "（游戏加载比较慢，点了之后耐心等一会儿）",
                                   style="DimCard.TLabel")
            self.btn_connect.configure(state="normal")

    # ================================================== ② 开关

    def refresh(self) -> None:
        """重建开关按钮与状态（_debug.txt 变化后调用）。"""
        for child in self.flag_box.winfo_children():
            child.destroy()
        self._flag_buttons.clear()

        df = self.app.debug
        if df is None or not df.exists():
            ttk.Label(self.flag_box, text="没找到游戏的开关文件（_debug.txt）——"
                                          "请先确认游戏目录设置正确。",
                      style="Card.TLabel").pack(anchor="w")
            self.lb_flag_note.configure(text="")
            self.refresh_connection()
            return

        vals = df.values()
        for key, label in QUICK_FLAGS:
            self._add_flag_button(key, label, vals.get(key) == 1)
        self._add_flag_button(F7_KEY, F7_LABEL,
                              vals.get("announce") == 1 and vals.get("timestamp") == 1)

        on = [label for key, label in QUICK_FLAGS if vals.get(key) == 1]
        self.lb_flag_note.configure(
            text=("已开启：" + "、".join(l.split(" ——")[0] for l in on)
                  + "　——　改完开关后要「重启游戏」才会生效。")
            if on else "目前全部关闭。")
        self.refresh_connection()

    def _add_flag_button(self, key: str, label: str, is_on: bool) -> None:
        text = f"{ON if is_on else OFF}　{label}"
        btn = ttk.Button(self.flag_box, text=text,
                         style="BigOn.TButton" if is_on else "Big.TButton",
                         command=lambda k=key: self._toggle_flag(k))
        btn.pack(fill="x", pady=pxs(3, 0))
        self._flag_buttons[key] = btn

    def _toggle_flag(self, key: str) -> None:
        df = self.app.debug
        if df is None:
            self.app.log("没找到 _debug.txt", "err")
            return
        if key == F7_KEY:
            vals = df.values()
            turn_on = not (vals.get("announce") == 1 and vals.get("timestamp") == 1)
            mapping = {"announce": 1 if turn_on else 0, "timestamp": 1 if turn_on else 0}
            what = "解锁" if turn_on else "关闭"
        else:
            mapping = {key: 0 if df.values().get(key) == 1 else 1}
            what = "开启" if mapping[key] else "关闭"
        if not df.set_many(mapping):
            self.app.log(f"写入失败：{df.last_error}", "err")
            messagebox.showerror("写入失败", f"{df.last_error}\n\n"
                                            "请确认游戏目录下的 _debug.txt 没有被其他程序占用。",
                                 parent=self)
            return
        name = F7_LABEL.split("（")[0] if key == F7_KEY else dict(QUICK_FLAGS)[key]
        self.app.log(f"已{what}：{name}　（重启游戏后生效）", "ok")
        self.refresh()

    def _all_flags_off(self) -> None:
        df = self.app.debug
        if df is None:
            return
        vals = df.values()
        mapping = {k: 0 for k, v in vals.items()
                   if k not in ("DEBUG", "benchmark") and v == 1}
        if not mapping:
            self.app.log("游戏开关本来就是全关的")
            return
        df.set_many(mapping)
        self.app.log("已把游戏调试开关全部关闭（重启游戏后生效）", "ok")
        self.refresh()

    def _restore_orig(self) -> None:
        df = self.app.debug
        if df is None:
            return
        if not df.orig_backup.exists():
            messagebox.showinfo("不用还原",
                                "这个工具还没有改过游戏的开关文件，所以没有可还原的版本。",
                                parent=self)
            return
        if not messagebox.askyesno(
                "确认还原", "把游戏的开关文件还原成本工具第一次修改之前的样子？\n\n"
                            "当前内容会先另存一份，随时还能再换回来。", parent=self):
            return
        if df.restore("orig"):
            self.app.log("已把游戏开关还原到最初的样子（重启游戏后生效）", "ok")
            self.refresh()
        else:
            self.app.log(f"还原失败：{df.last_error}", "err")

    # ================================================== ③ 找数值

    def _hotkey_hint(self) -> str:
        """把 F8 / F9 这类热键提示拼出来（热键被关掉时就不提）。"""
        if not self.app.cfg.get("hotkeys_enabled", True):
            return ""
        keys = self.app.cfg.get("hotkeys", {})
        small, big = keys.get("smaller", ""), keys.get("bigger", "")
        if not small and not big:
            return ""
        parts = [f"{k} = {n}" for k, n in ((small, "变小了"), (big, "变大了")) if k]
        return "（在游戏里直接按 " + "、".join(parts) + "，不用切回这个窗口）"

    def _purpose(self):
        return list(PURPOSES.values())[self.cb_purpose.current()]

    def _on_purpose(self) -> None:
        purpose = self._purpose()
        self.lb_ask.configure(text=purpose.what + "是多少？")
        self.e_lock.delete(0, "end")
        self.e_lock.insert(0, str(purpose.lock))
        self._reset(keep_value=False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_begin.configure(state="disabled" if busy else "normal")

    def _begin(self) -> None:
        app = self.app
        if self._busy:
            return
        if not (app.proc and app.proc.opened and app.proc.alive()):
            messagebox.showinfo("还没连上游戏",
                                "请先在上面第 1 步连上游戏，再回来找数值。", parent=self)
            return
        raw = self.e_value.get().strip()
        try:
            value = int(raw, 0)
        except ValueError:
            app.log(f"「{raw}」不是个数字，请填游戏里看到的数量", "err")
            self.lb_tip.configure(text="提示：只能填纯数字，比如 137。不要带单位或符号。")
            return

        purpose = self._purpose()
        self.wizard = Wizard(app.proc,
                             include_readonly=app.tab_scan.v_ro.get(),
                             include_mapped=app.tab_scan.v_mapped.get())
        self._set_busy(True)
        self.lb_state.configure(text="正在找……（大概几秒）")
        self.lb_tip.configure(text="")
        self._enable_steps(False)
        self._fill_tree([])

        def work(progress, cancelled):
            return self.wizard.begin(value, progress=progress, cancelled=cancelled)

        self.task = run_async(self, work, on_done=self._begin_done,
                              on_error=self._begin_error,
                              on_progress=self._begin_progress)

    def _begin_progress(self, frac: float, text: str) -> None:
        """扫描要读几百 MB，得让用户看到它在动。"""
        self.lb_state.configure(text=f"正在找…… {max(0, min(100, int(frac * 100)))}%")

    def _begin_done(self, report) -> None:
        self._set_busy(False)
        if not report.chosen:
            tried = report.describe_hits() or "无"
            self.lb_state.configure(text="没找到这个数字。")
            self.lb_tip.configure(
                text=f"各宽度命中情况：{tried}。\n"
                     f"请检查：① 数字有没有看错；② 游戏里显示的数字和实际存的可能差 10 倍"
                     f"（试试填 1370 或 13）；③ 换个「要找什么」再试。")
            self.app.log(f"自动查找失败：各宽度命中 {tried}", "warn")
            return

        purpose = self._purpose()
        self.lb_state.configure(
            text=f"找到了 {report.count} 个可能的位置（先不用管有多少个）。")
        self.lb_tip.configure(
            text=f"现在去游戏里把它【变小】：{purpose.smaller}\n"
                 f"做完点左边那个蓝色的大按钮 {self._hotkey_hint()}")
        self._enable_steps(True)
        self._fill_tree(self.wizard.candidates(limit=30))
        self.app.log(f"自动查找：按 {report.scanner.vt.label} 统计共 {report.count} 个候选"
                     f"（各宽度命中 {report.describe_hits()}）", "ok")

    def _begin_error(self, exc: Exception) -> None:
        self._set_busy(False)
        self.app.log(f"查找失败：{exc!r}", "err")
        self.lb_state.configure(text="出错了，请看下面日志。")

    def _narrow(self, bigger: bool) -> None:
        if not (self.wizard and self.wizard.active):
            self.lb_tip.configure(text="请先在上面填好数字、点「开始找」。")
            return
        purpose = self._purpose()
        n = self.wizard.narrow(bigger)
        self._after_narrow(n, purpose)

    def hotkey_narrow(self, bigger: bool) -> None:
        """游戏里按 F8 / F9 的回调：等价于点「变小了 / 变大了」。

        热键不需要用户在游戏和工具之间来回切，所以是这条流程最省事的用法。
        """
        if not (self.wizard and self.wizard.active):
            self.app.log(f"热键「{'变大' if bigger else '变小'}了」：现在没有在找数值，"
                         f"请先到「一键」页填好数字点「开始找」", "warn")
            return
        purpose = self._purpose()
        n = self.wizard.narrow(bigger)
        self.app.log(f"（热键）按你说的「{'变大' if bigger else '变小'}了」筛了一轮 → "
                     f"剩 {n} 个", "ok")
        self._after_narrow(n, purpose)

    def _after_narrow(self, n: int, purpose) -> None:
        if n == 0:
            self.lb_state.configure(text="一个都没剩下 —— 这次没筛对。")
            self.lb_tip.configure(
                text="可能的原因：① 你还没真的让数字变化；② 数字是往另一个方向变的，"
                     "那就点另一个按钮；③ 前一次点错了。\n点「重新开始」再来一遍即可。")
            self._enable_steps(False)
            self._fill_tree([])
            return

        if n <= DONE_THRESHOLD and n > 0:
            self._fill_tree(self.wizard.candidates(limit=30))
            targets = self.wizard.targets()
            if len(targets) == 1:
                first = self.wizard.candidates(limit=1)[0]
                self.lb_state.configure(
                    text=f"✅ 找到了！就这一个位置：{fmt_addr(first[0])}　当前数值 {first[1]}")
                detail = ""
            else:
                self.lb_state.configure(
                    text=f"✅ 找到了！有 {len(targets)} 个位置始终一起变化 —— "
                         f"它们是同一个数值的多份拷贝，不用区分，一起锁定就行。")
                detail = "（这几个位置永远是同一个值，所以随便挑哪一个都一样，工具会一起锁上）\n"
            self.lb_tip.configure(
                text=f"核对一下：这个数值和游戏里显示的是否一样？\n" + detail +
                     f"确认没问题就点下面「锁定它」——之后这个数值不会再变"
                     f"（金币花不掉 / 物品用不完）。")
            self.btn_lock.configure(state="normal")
            self.btn_save.configure(state="normal")
            self.app.log(f"找到目标：{len(targets)} 处（{self.wizard.rounds} 轮收敛）；"
                         f"首个 {fmt_addr(targets[0])}", "ok")
            return

        self._fill_tree(self.wizard.candidates(limit=30))
        self.btn_lock.configure(state="disabled")
        self.btn_save.configure(state="disabled")
        self.lb_state.configure(text=f"还剩 {n} 个可能的位置。")
        nxt_small = purpose.smaller
        self.lb_tip.configure(
            text=f"再让它变一次（{nxt_small}），然后回来再点一次蓝色大按钮。\n"
                 f"通常再点 1~2 次就有结果了。{self._hotkey_hint()}")

    def _enable_steps(self, on: bool) -> None:
        state = "normal" if on else "disabled"
        self.btn_smaller.configure(state=state)
        self.btn_bigger.configure(state=state)

    def _reset(self, keep_value: bool = True) -> None:
        if self.wizard:
            self.wizard.reset()
        self.wizard = None
        if not keep_value:
            self.e_value.delete(0, "end")
        self._enable_steps(False)
        self.btn_lock.configure(state="disabled")
        self.btn_save.configure(state="disabled")
        self._fill_tree([])
        self.lb_state.configure(text="")
        purpose = self._purpose()
        self.lb_tip.configure(
            text=f"用法：先在游戏里看一眼{purpose.what}，填到左边的框里，点「开始找」；"
                 f"然后回游戏让这个数字变化，再回来点下面的大按钮。")

    def _fill_tree(self, rows) -> None:
        self.tree.delete(*self.tree.get_children())
        for addr, value in rows:
            self.tree.insert("", "end", values=(fmt_addr(addr), fmt_value(
                self.wizard.scanner.vt, value) if self.wizard and self.wizard.scanner else value))

    # ---------------------------------------- 锁定 / 预设

    def _selected_addr(self) -> int | None:
        """用户在列表里选中的地址；没选就用收敛出的第一处。"""
        sel = self.tree.selection()
        if sel:
            return self._parse_addr(self.tree.item(sel[0], "values")[0])
        targets = self.wizard.targets() if self.wizard else []
        return targets[0] if targets else None

    def _lock(self) -> None:
        app = self.app
        if not (self.wizard and self.wizard.active):
            return
        purpose = self._purpose()
        try:
            value = int(self.e_lock.get().strip(), 0)
        except ValueError:
            app.log("锁定值必须是数字", "err")
            return

        # 用户明确选了某一行就只锁那一行；否则把剩下的候选全部锁上
        # （同一数值的多份拷贝必须一起按，否则游戏可能读的是另一份）
        picked = self.tree.selection()
        if picked:
            addrs = [a for a in (self._parse_addr(self.tree.item(i, "values")[0])
                                 for i in picked) if a]
        else:
            addrs = self.wizard.targets()
        if not addrs:
            messagebox.showinfo("先选一个", "请在上面列表里点一下要锁定的那一行。", parent=self)
            return

        vt = self.wizard.scanner.vt
        for i, addr in enumerate(addrs):
            label = purpose.name if i == 0 else f"{purpose.name}（第 {i + 1} 处拷贝）"
            app.freezer.add_lock(label, Target(kind="direct", addr=addr), vt, value,
                                 slot=purpose.slot if i == 0 else "")
        app.log(f"已锁定「{purpose.name}」= {value}"
                + (f"（{len(addrs)} 个位置）" if len(addrs) > 1 else
                   f"（地址 {fmt_addr(addrs[0])}）"), "ok")
        if purpose.slot:
            hotkey = app.cfg.get("hotkeys", {}).get(purpose.slot, "")
            if hotkey:
                app.log(f"提示：在游戏里按 {hotkey} 也能随时开关这个锁定", "dim")
        self.lb_tip.configure(
            text=f"已锁定为 {value}，游戏里这个数值不会再减少了。\n"
                 f"想取消锁定：去「锁定 / 监视」页停用它，或者点本页最下面的"
                 f"「停用全部锁定」。")
        app.goto_tab("locked")

    @staticmethod
    def _parse_addr(text) -> int | None:
        try:
            return int(str(text), 16)
        except (TypeError, ValueError):
            return None

    def _save_preset(self) -> None:
        app = self.app
        if not (self.wizard and self.wizard.active):
            return
        addr = self._selected_addr()
        if addr is None:
            return
        purpose = self._purpose()
        try:
            value = int(self.e_lock.get().strip(), 0)
        except ValueError:
            value = purpose.lock
        preset = pr.make_preset(
            purpose.name, Target(kind="direct", addr=addr),
            self.wizard.scanner.vt, value, lock=True, slot=purpose.slot,
            note=f"「一键」页自动找到（{fmt_addr(addr)}）")
        app.cfg["presets"] = pr.replace_or_add(app.cfg.get("presets", []), preset)
        app.save_cfg()
        app.log(f"已存为预设「{purpose.name}」——下次连上游戏会自动套用，不用再找一遍", "ok")
        self.lb_tip.configure(
            text="已存为预设。注意：直接地址在游戏重启后会变，"
                 "如果哪次发现锁定无效，回来重新找一遍再存一次即可。")
        app.tab_presets.refresh()

    # ---------------------------------------- 还原

    def _disable_locks(self) -> None:
        n = sum(1 for e in self.app.freezer.locks.values() if e.enabled)
        if not n:
            self.app.log("当前没有生效中的锁定")
            return
        for e in self.app.freezer.locks.values():
            self.app.freezer.set_lock_enabled(e.uid, False)
        self.app.log(f"已停用全部锁定（{n} 项）——游戏里的数值恢复正常变化", "ok")
        self.app.tab_locked.refresh()
