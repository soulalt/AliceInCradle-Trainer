# -*- coding: utf-8 -*-
"""P9 自测：「一键」页的傻瓜流程 —— 填一次数字 → 点「变小了」→ 锁定。

这是本轮改动的核心承诺：新手不需要懂字节宽度、筛选模式、地址，
只要「填一次数字 + 在变化后点一下按钮」就能定位并锁定。

测试用一个可远程改值的子进程冒充游戏（4096 个槽位全是同一个数字，
精确扫描必然命中一大堆，只有靠"变化"才能挑出真正那一个）：

    ① 直接测 core.autofind.Wizard 的收敛
    ② 造真实界面，走一遍 填数 → 开始找 → 变小了 → 锁定 → 存预设
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 配置隔离到临时目录：自测不该写脏用户真实的 config/trainer.json
os.environ["AIC_CONFIG_DIR"] = tempfile.mkdtemp(prefix="aic_test_cfg_")

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def pump(app, times: int = 6, delay: float = 0.05) -> None:
    for _ in range(times):
        app.update_idletasks()
        app.update()
        time.sleep(delay)


def wait_until(app, cond, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        pump(app, 1, 0.05)
        if cond():
            return True
    return False


class Child:
    """可远程改值的子进程。"""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-u", os.path.join(ROOT, "tests", "_child_wizard.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        self.addr = int(self.proc.stdout.readline().strip(), 16)
        ready = self.proc.stdout.readline().strip()
        self.initial = int(ready.split()[1])

    @property
    def pid(self) -> int:
        return self.proc.pid

    def set(self, value: int) -> int:
        self.proc.stdin.write(f"set {value}\n")
        self.proc.stdin.flush()
        return int(self.proc.stdout.readline().strip().split()[1])

    def get(self) -> int:
        self.proc.stdin.write("get\n")
        self.proc.stdin.flush()
        return int(self.proc.stdout.readline().strip().split()[1])

    def kill(self) -> None:
        try:
            self.proc.stdin.write("quit\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def test_core_wizard(child: Child) -> None:
    """不经界面，先验证收敛逻辑本身。"""
    from core import winmem
    from core.autofind import Wizard

    proc = winmem.Process(child.pid)
    assert proc.open(), proc.last_error
    try:
        wiz = Wizard(proc)
        report = wiz.begin(child.initial)
        check("首扫自动选了宽度并命中", report.chosen != "" and report.count > 0,
              f"各宽度命中 {report.hits}，候选 {report.count}")
        check("四种宽度都被保留下来一起收敛", len(report.probes) >= 2,
              str([(p.key, p.count) for p in report.probes]))

        # 只有目标地址会变；让它变小，向导应该把目标留在候选里
        before = report.count          # 注意 report 是实时的，必须先取值
        child.set(child.initial - 1)
        n1 = wiz.narrow(False)
        rows1 = wiz.candidates(limit=50)
        check("一次「变小了」后候选显著收敛", n1 < before, f"{before} → {n1}")
        check("目标地址仍在候选里", any(a == child.addr for a, _v in rows1),
              f"剩 {n1} 个")
        check("读到的当前值与子进程一致",
              all(int(v) == child.initial - 1 for _a, v in rows1),
              f"{[v for _a, v in rows1][:4]} vs {child.initial - 1}")

        # 再变一次，应该收敛到「可以一起锁定」的程度
        child.set(child.initial - 2)
        n2 = wiz.narrow(False)
        check("再点一次后收敛到可直接锁定的程度", wiz.solved, f"剩 {n2} 个")
        check("剩下的候选永远同值（是同一数值的多份拷贝）", wiz.all_same(),
              str([v for _a, v in wiz.candidates(limit=5)]))
        check("目标地址就在这批候选里", child.addr in wiz.targets(),
              "、".join(hex(a) for a in wiz.targets()))
        check("每一处候选的值都跟着变",
              all(int(v) == child.initial - 2 for _a, v in wiz.candidates(limit=5)),
              str([v for _a, v in wiz.candidates(limit=5)]))

        # 反方向：用「变大了」按钮也应该能收敛
        wiz2 = Wizard(proc)
        wiz2.begin(child.initial - 2)
        child.set(child.initial)
        wiz2.narrow(True)
        child.set(child.initial + 5)
        n2b = wiz2.narrow(True)
        rows2 = wiz2.candidates(limit=20)
        check("「变大了」按钮同样能定位到目标", any(a == child.addr for a, _v in rows2),
              f"剩 {n2b} 个")

        # 方向点错：候选归零，界面应提示重来
        wiz3 = Wizard(proc)
        wiz3.begin(child.initial + 5)
        n3 = wiz3.narrow(False)          # 其实没让值变小
        check("方向点错时候选归零（界面会提示重来）", n3 == 0, f"剩 {n3} 个")
    finally:
        proc.close()


def test_ui_flow(child: Child) -> None:
    """走真实界面：填数 → 开始找 → 变小了 → 锁定 → 存预设。"""
    from core import paths
    from ui.main_window import TrainerApp

    cfg = paths.load_config()
    cfg["hotkeys_enabled"] = False
    cfg["auto_attach"] = False           # 避免测试期间自动连到别的进程
    cfg["autobackup_saves"] = False
    cfg["game_dir"] = os.path.dirname(ROOT)   # 本工具就在游戏目录里，填上省一次磁盘探测
    cfg["presets"] = []
    paths.save_config(cfg)

    app = TrainerApp()
    pump(app, 8)
    ok = app.attach(child.pid)
    pump(app, 6)
    check("界面已连上被测进程", ok)

    tab = app.tab_onekey
    check("默认打开的就是「一键」页", app._current_tab() == "onekey", app._current_tab())
    check("「一键」页列出了 5 个游戏开关按钮", len(tab._flag_buttons) == 5,
          str(list(tab._flag_buttons)))

    child.set(child.initial)
    tab.e_value.delete(0, "end")
    tab.e_value.insert(0, str(child.initial))
    tab._begin()
    # 扫描在后台线程跑，界面回调稍后才把按钮点亮，所以等到按钮真的可用为止
    wait_until(app, lambda: tab.wizard is not None and tab.wizard.active
               and str(tab.btn_smaller.cget("state")) == "normal", timeout=30)
    check("界面上「开始找」有结果", tab.wizard is not None and tab.wizard.active,
          tab.lb_state.cget("text"))
    check("开始后「变小了」按钮可用", str(tab.btn_smaller.cget("state")) == "normal",
          str(tab.btn_smaller.cget("state")))
    check("未收敛前锁定按钮是禁用的", str(tab.btn_lock.cget("state")) == "disabled")
    first_count = tab.wizard.count

    # 第 1 次：让被监控的数值变小，然后按「变小了」
    child.set(child.initial - 1)
    tab._narrow(False)
    pump(app, 4)
    check("第 1 次「变小了」后候选明显变少", tab.wizard.count < first_count,
          f"{first_count} → {tab.wizard.count}")
    check("目标地址已经在候选里",
          any(a == child.addr for a, _v in tab.wizard.candidates(limit=50)))

    # 第 2 次：再变一次 → 收敛到可直接锁定
    child.set(child.initial - 2)
    tab._narrow(False)
    pump(app, 4)
    check("第 2 次后可以锁定了", tab.wizard.solved, tab.lb_state.cget("text"))
    check("提示里给出了找到的位置", "找到" in tab.lb_state.cget("text"),
          tab.lb_state.cget("text"))
    check("锁定按钮变为可用", str(tab.btn_lock.cget("state")) == "normal")

    # 锁定它 —— 子进程里的值应该被按住
    tab._lock()
    pump(app, 16)
    entry = app.freezer.find_lock_by_slot("add_money")
    check("锁定项已建立并绑定了金币槽位", entry is not None,
          str([(e.label, e.slot) for e in app.freezer.locks.values()]))
    addrs = [e.target.addr for e in app.freezer.locks.values()]
    check("锁定覆盖了子进程里那个地址", child.addr in addrs,
          "、".join(hex(a) for a in addrs))
    check("同一数值的多份拷贝被一起锁上（否则游戏可能读的是另一份）",
          len(addrs) >= 1, f"{len(addrs)} 处")
    check("所有锁定项的值都是 999999",
          all(int(e.value) == 999999 for e in app.freezer.locks.values()),
          str([e.value for e in app.freezer.locks.values()]))
    check("「用途」预设把锁定值填成了 999999", tab.e_lock.get() == "999999",
          tab.e_lock.get())
    got = child.get()
    check("子进程的数值真的被改成了 999999（锁定生效）", got == 999999, f"读到 {got}")

    # 存成预设：以后连上游戏会自动套用
    tab._save_preset()
    pump(app, 2)
    from core import presets as pr
    saved = pr.find_by_slot(app.cfg.get("presets", []), "add_money")
    check("已存为 add_money 预设", saved is not None,
          str([(p.get("name"), p.get("slot")) for p in app.cfg.get("presets", [])]))

    # 还原入口：停用全部锁定后，子进程的值不再被按住
    tab._disable_locks()
    pump(app, 4)
    check("「停用全部锁定」后没有启用中的锁定",
          all(not e.enabled for e in app.freezer.locks.values()))

    app._ask_quit = True
    app.freezer.stop()
    app.hotkeys.stop()
    if app.proc:
        app.proc.close()
    app.destroy()


def main() -> int:
    child = Child()
    try:
        check("子进程就绪", child.proc.poll() is None,
              f"地址 {hex(child.addr)}，初始值 {child.initial}")
        try:
            test_core_wizard(child)
        except Exception:
            traceback.print_exc()
            check("核心收敛流程", False, "见上文异常")

        child.set(child.initial)
        try:
            test_ui_flow(child)
        except Exception:
            traceback.print_exc()
            check("界面傻瓜流程", False, "见上文异常")
    finally:
        child.kill()

    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
