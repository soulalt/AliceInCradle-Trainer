# -*- coding: utf-8 -*-
"""P8 自测：改完「界面缩放」后的自动重启是否真的把新窗口拉起来。

顶栏切换缩放会问用户「是否立即重启」，点是就走 `TrainerApp._restart()`：
先 Popen 一个新实例，再关掉自己。这条路径容易被改坏（比如把参数写错、
关掉自己时把新进程也一起带走），所以单独验一次：

    造窗口 → 调 _restart() → 轮询等新窗口出现 → 关掉它 → 还原配置

注意：测试期间会短暂占用真实配置文件，结束时还原；不会碰游戏文件。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置隔离到临时目录：自测不该写脏用户真实的 config/trainer.json
os.environ["AIC_CONFIG_DIR"] = tempfile.mkdtemp(prefix="aic_test_cfg_")

import close_trainer as ct                     # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def main() -> int:
    from core import paths
    from ui.main_window import TrainerApp

    cfg = paths.load_config()
    cfg["ui_scale"] = "auto"
    cfg["window_geometry"] = ""
    cfg["hotkeys_enabled"] = False       # 别抢用户的 F1~F5
    cfg["autobackup_saves"] = False
    cfg["auto_attach"] = False
    cfg["game_dir"] = os.path.dirname(ROOT)
    paths.save_config(cfg)

    # 起手先清掉可能残留的窗口，避免误判
    ct.close_all()
    time.sleep(1.0)
    check("起手没有残留的修改器窗口", not ct.find_windows(), str(ct.find_windows()))

    app = TrainerApp()
    for _ in range(10):
        app.update_idletasks()
        app.update()
        time.sleep(0.05)

    my_pid = os.getpid()
    old = ct.find_windows()
    check("自己这个窗口已经建起来", len(old) == 1, str(old))

    spawned = 0
    try:
        app._restart()
        check("_restart() 后旧窗口已关闭", not ct.find_windows(), str(ct.find_windows()))

        # 等新实例把窗口显示出来（python 启动 + 探测游戏目录，给足时间）
        deadline = time.time() + 40
        while time.time() < deadline:
            wins = ct.find_windows()
            if wins:
                spawned = len(wins)
                break
            time.sleep(0.5)
        check("新实例的窗口已经出现", spawned >= 1, f"等了 {40 - int(deadline - time.time())}s")
        if spawned:
            new = ct.find_windows()
            check("新窗口不是旧进程（PID 不同）",
                  all(pid != my_pid for _h, pid, _t in new), str(new))
            check("新窗口标题带版本号",
                  all("修改器 v" in t for _h, _p, t in new),
                  "、".join(t for _h, _p, t in new))
    finally:
        closed = ct.close_all()
        print(f"已关闭 {closed} 个测试窗口")
        time.sleep(2.0)
        ct.close_all()                    # 再兜一次，防止有窗口迟到

    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
