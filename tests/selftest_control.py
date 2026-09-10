# -*- coding: utf-8 -*-
"""P4 自测：锁定/监视线程、全局热键解析与注册、预设持久化。"""

from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import winmem  # noqa: E402
from core import presets as pr  # noqa: E402
from core.freezer import Freezer, Target  # noqa: E402
from core.hotkeys import HotkeyManager, parse_hotkey  # noqa: E402
from core.scanner import VALUE_TYPES  # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def main() -> int:
    # ---------------- 热键解析 ----------------
    cases = {
        "F1": None, "Ctrl+Alt+1": None, "Ctrl+Shift+S": None,
        "Alt+F12": None, "`": None, "Ctrl+`": None,
    }
    for text in cases:
        try:
            mods, vk = parse_hotkey(text)
            print(f"      {text:<12} -> mods=0x{mods:X} vk=0x{vk:02X}")
        except ValueError as exc:
            check(f"解析热键 {text}", False, str(exc))
            continue
    check("F1 解析为 VK 0x70", parse_hotkey("F1")[1] == 0x70)
    check("Ctrl+Alt+1 修饰位正确", parse_hotkey("Ctrl+Alt+1")[0] & 0x0003 == 0x0003)
    try:
        parse_hotkey("Ctrl+")
        check("非法热键应报错", False)
    except ValueError:
        check("非法热键应报错", True)

    # ---------------- 热键注册/注销 ----------------
    hk = HotkeyManager()
    failures = hk.start({"a": "Ctrl+Alt+F9", "b": "Ctrl+Alt+F10"})
    check("全局热键注册成功（无失败项）", failures == {}, str(failures))
    check("热键管理器进入启用态", hk.enabled)
    check("热键轮询接口可用", hk.poll() == [])
    check("可临时禁用全部热键", hk.set_enabled(False) == {} and not hk.enabled)

    # ---------------- 锁定 / 监视 ----------------
    child = subprocess.Popen(
        [sys.executable, "-u", os.path.join(ROOT, "tests", "_child_probe.py")],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        addr = int(child.stdout.readline().strip(), 16)
        proc = winmem.Process(child.pid)
        assert proc.open(), proc.last_error

        fz = Freezer(proc)
        fz.start()
        entry = fz.add_lock("测试锁定", Target(kind="direct", addr=addr),
                            VALUE_TYPES["4bytes"], 777, enabled=True)
        time.sleep(0.6)
        vals = [child.stdout.readline().strip() for _ in range(4)]
        check("锁定生效：子进程回读恒为 777", vals[-2:] == ["777", "777"], str(vals))
        check("锁定项记录了写入次数", entry.writes > 0, f"writes={entry.writes}")

        fz.set_lock_enabled(entry.uid, False)
        time.sleep(0.4)
        check("解除锁定后不再回写", fz.get_lock(entry.uid).enabled is False)

        m = fz.add_monitor("测试监视", Target(kind="direct", addr=addr), VALUE_TYPES["4bytes"])
        time.sleep(0.4)
        locks, mons = fz.snapshot()
        check("监视表能读到当前值", mons and mons[0].value is not None, f"值={mons[0].value}")

        # 指针链解析：模块不存在时应安全返回 None
        bad = Target(kind="pointer", module="不存在的模块.dll", offsets=[0x10, 0x20])
        check("非法指针链安全失败", bad.resolve(fz._ctx) is None, bad.describe())

        fz.stop()
        check("锁定线程可正常停止", fz._thread is None)
        proc.close()
    finally:
        child.kill()
        child.wait(timeout=5)

    # ---------------- 预设 ----------------
    cfg_presets: list[dict] = []
    t = Target(kind="direct", addr=0x1234ABCD)
    p = pr.make_preset("金币", t, VALUE_TYPES["4bytes"], 999999, slot="add_money", note="商店")
    cfg_presets = pr.replace_or_add(cfg_presets, p)
    check("新增预设", len(cfg_presets) == 1)
    p2 = pr.make_preset("金币", t, VALUE_TYPES["4bytes"], 500, slot="add_money")
    cfg_presets = pr.replace_or_add(cfg_presets, p2)
    check("同 slot 覆盖而非重复添加",
          len(cfg_presets) == 1 and cfg_presets[0]["value"] == 500)
    check("按 slot 查找", pr.find_by_slot(cfg_presets, "add_money") is not None)
    cfg_presets = pr.remove(cfg_presets, "金币")
    check("删除预设", cfg_presets == [])
    check("指针预设序列化往返",
          Target.from_dict(Target(kind="pointer", module="mono-2.0-bdwgc.dll",
                                  offsets=[0x10, 0x28]).to_dict()).describe()
          == "mono-2.0-bdwgc.dll+0x10+0x28")

    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
