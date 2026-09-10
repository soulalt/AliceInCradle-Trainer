# -*- coding: utf-8 -*-
"""跨进程端到端自测：附加真实子进程 -> 扫描定位 -> 写入 -> 由子进程回读确认。"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import winmem  # noqa: E402
from core import scanner as sc  # noqa: E402

MAGIC = 0x1A2B3C4D
NEW = 0x00C0FFEE

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def main() -> int:
    child = subprocess.Popen(
        [sys.executable, "-u", os.path.join(ROOT, "tests", "_child_probe.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        addr_line = child.stdout.readline().strip()
        assert addr_line, "子进程未回报地址"
        addr = int(addr_line, 16)
        pid = child.pid
        print(f"子进程 pid={pid}  缓冲区地址=0x{addr:X}\n")

        check("按名字枚举能找到子进程", winmem.find_pid_by_name("python.exe") is not None)

        proc = winmem.Process(pid)
        check("跨进程 OpenProcess 成功", proc.open(), proc.last_error)
        if not proc.opened:
            return 1

        mods = proc.modules()
        check("子进程模块枚举非空", len(mods) > 0, f"{len(mods)} 个模块")
        regs = proc.regions()
        total = sum(r.size for r in regs)
        check("子进程可写区域枚举非空", len(regs) > 0,
              f"{len(regs)} 个区域 / {total/1048576:.1f} MB")

        raw = proc.read(addr, 4)
        check("按已知地址读取到 MAGIC",
              raw == struct.pack("<i", MAGIC), f"{raw.hex() if raw else None}")

        # 扫描整个子进程，确认能定位到该地址
        t0 = time.time()
        s = sc.Scanner(proc, sc.VALUE_TYPES["4bytes"])
        n = s.first_scan(sc.EXACT, MAGIC)
        dt = time.time() - t0
        check("跨进程精确扫描命中目标地址", addr in s.addrs,
              f"命中 {n} 个 / 用时 {dt:.2f}s / 扫描 {total/1048576:.0f}MB")

        # 写入并由子进程回读确认
        child.stdout.readline()  # 丢弃一行旧值
        check("写入新值成功", s.write(addr, NEW))
        newval = child.stdout.readline().strip()
        check("子进程回读确认写入生效", newval == str(NEW), f"子进程读到 {newval}")

        proc.close()
    finally:
        child.kill()
        child.wait(timeout=5)

    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
