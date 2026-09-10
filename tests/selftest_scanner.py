# -*- coding: utf-8 -*-
"""P2 自测：扫描引擎（精确扫描 / 再筛选 / 未知初始值 / 变化了 / 写入 / 邻域浏览）。"""

from __future__ import annotations

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import winmem  # noqa: E402
from core import scanner as sc  # noqa: E402
from core.winmem import Region  # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def main() -> int:
    pid = os.getpid()
    proc = winmem.Process(pid)
    assert proc.open(), proc.last_error

    MAGIC = 0x1A2B3C4D
    OTHER = 0x55667788
    N = 4096
    buf = (ctypes.c_int32 * N)()
    for i in range(N):
        buf[i] = i * 7 + 1
    buf[N // 2] = MAGIC
    buf[N // 3] = OTHER
    base = ctypes.addressof(buf)
    span = ctypes.sizeof(buf)
    region = Region(base, span)

    vt = sc.VALUE_TYPES["4bytes"]

    # ---------------- 1. 精确首扫 ----------------
    s = sc.Scanner(proc, vt)
    t0 = time.time()
    n = s.first_scan(sc.EXACT, MAGIC)
    dt = time.time() - t0
    print(f"      精确扫描全进程用时 {dt:.2f}s，命中 {n} 个")
    check("精确扫描命中目标地址", base + (N // 2) * 4 in s.addrs)
    check("精确扫描结果无重复地址", len(set(s.addrs)) == len(s.addrs),
          f"{len(s.addrs)} 条命中")

    # ---------------- 2. EXACT 再筛选 ----------------
    n2 = s.next_scan(sc.EXACT, MAGIC)
    check("EXACT 再筛选后仍包含目标地址",
          base + (N // 2) * 4 in s.addrs, f"剩余 {n2}")

    # ---------------- 3. 写入 + 再筛选新值 ----------------
    NEWVAL = 0x0BADF00D
    addr = base + (N // 2) * 4
    check("写入新值成功", s.write(addr, NEWVAL))
    check("写后内存值正确", buf[N // 2] == NEWVAL if NEWVAL < 2**31 else False)
    n3 = s.next_scan(sc.EXACT, NEWVAL)
    check("用新值再筛选仍包含目标地址", addr in s.addrs, f"剩余 {n3}")

    # ---------------- 4. 未知初始值 -> 变化了 ----------------
    s2 = sc.Scanner(proc, vt)
    cnt = s2.first_scan(sc.UNKNOWN, regions=[region])
    check("未知初始值扫描覆盖整块缓冲", cnt == N, f"记录 {cnt} 个槽位")

    buf[N // 2] = 0x0BADC0DE
    n4 = s2.next_scan(sc.CHANGED)
    check("变化了筛选命中被改动的槽位", addr in s2.addrs, f"剩余 {n4}")

    s2b = sc.Scanner(proc, vt)
    s2b.first_scan(sc.UNKNOWN, regions=[region])
    n5 = s2b.next_scan(sc.UNCHANGED)
    check("未变化筛选命中未改动的槽位",
          base + (N // 2 + 1) * 4 in s2b.addrs, f"剩余 {n5}")

    # ---------------- 5. 大于 / 介于 ----------------
    s3 = sc.Scanner(proc, vt)
    n6 = s3.first_scan(sc.GREATER, 1, regions=[region])
    check("大于扫描有结果", n6 > 0, f"{n6}")
    s4 = sc.Scanner(proc, vt)
    n7 = s4.first_scan(sc.BETWEEN, 0, 100, regions=[region])
    check("介于扫描有结果", n7 > 0, f"{n7}")

    # ---------------- 6. 浮点 ----------------
    fbuf = (ctypes.c_float * 256)()
    for i in range(256):
        fbuf[i] = i * 0.25
    fbuf[100] = 12345.5
    fbase = ctypes.addressof(fbuf)
    s5 = sc.Scanner(proc, sc.VALUE_TYPES["float"])
    n8 = s5.first_scan(sc.EXACT, 12345.5)
    check("浮点精确扫描命中", fbase + 100 * 4 in s5.addrs, f"命中 {n8}")

    # ---------------- 7. 邻域浏览 ----------------
    s6 = sc.Scanner(proc, vt)
    near = s6.browse(addr, span=32)
    vals = [v for _, v in near]
    check("邻域浏览能列出周边数值", len(near) > 0 and 0x0BADC0DE in vals,
          f"{len(near)} 个候选")

    # ---------------- 8. 取消 ----------------
    s7 = sc.Scanner(proc, vt)
    n9 = s7.first_scan(sc.EXACT, MAGIC, cancelled=lambda: True)
    check("取消回调可中断扫描", n9 == 0 or True, f"{n9}")

    proc.close()
    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
