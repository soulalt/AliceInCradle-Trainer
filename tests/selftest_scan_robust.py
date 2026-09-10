# -*- coding: utf-8 -*-
"""P2b 自测：扫描引擎的读取容错。

背景：真实场景里 `regions()` 的区域快照会过时（地址空间随时在变），一块 8MB 里
只要夹进一页读不到的页，旧的「整块读失败就整块放弃」会静默丢掉整个区域 ——
表现为「精确扫描偶尔漏掉目标地址」。

本测试用 VirtualAlloc 拿页对齐内存，人为把中间一页变成读不到，
验证：两侧的数据都还能扫到、命中无重复、只丢真正读不到的那一页。
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import scanner as sc  # noqa: E402
from core import winmem  # noqa: E402
from core.winmem import Region  # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


PAGE = 0x1000
MEM_COMMIT_RESERVE = 0x3000
PAGE_READWRITE = 0x04


def main() -> int:
    proc = winmem.Process(os.getpid())
    assert proc.open(), proc.last_error

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.VirtualAlloc.restype = ctypes.c_void_p
    k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                 wintypes.DWORD, wintypes.DWORD]
    k32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]

    span = 4 * PAGE
    base = int(k32.VirtualAlloc(None, span, MEM_COMMIT_RESERVE, PAGE_READWRITE))
    assert base, "VirtualAlloc 失败"
    region = Region(base, span)
    vt = sc.VALUE_TYPES["4bytes"]

    try:
        # 整块填 0，并在 4 页各放一个唯一值（第 3 页会被「毒化」）
        for off in range(0, span, 4):
            ctypes.c_int32.from_address(base + off).value = 0
        A, B, C, D = 0x11223344, 0x22334455, 0x33445566, 0x44556677
        for n, val in enumerate((A, B, C, D)):
            ctypes.c_int32.from_address(base + n * PAGE + 0x10).value = val
        addr_a = base + 0x10
        addr_b = base + PAGE + 0x10
        addr_c = base + 2 * PAGE + 0x10          # 落在毒页里
        addr_d = base + 3 * PAGE + 0x10

        # ---------------- 人为制造「第 3 页读不到」 ----------------
        poison_lo, poison_hi = base + 2 * PAGE, base + 3 * PAGE
        orig_read = winmem.Process.read

        def patched_read(self, addr, size):
            if addr < poison_hi and addr + size > poison_lo:
                return None                      # 整块读越到毒页就失败（与真实 RPM 一致）
            return orig_read(self, addr, size)

        winmem.Process.read = patched_read
        try:
            # ---------------- 1. read_pieces 只丢毒页 ----------------
            pieces = proc.read_pieces(base, span)
            got = sorted((a - base, len(d)) for a, d in pieces)
            check("read_pieces 只丢读不到的那一页",
                  got == [(0, 2 * PAGE), (3 * PAGE, PAGE)], f"{got}")
            check("read_pieces 把相邻可读页合并成一片",
                  len(pieces) == 2, f"{len(pieces)} 个片段")

            # ---------------- 2. 精确扫描：可读页都能命中，毒页的值确实丢了 ----------------
            for name, addr, val, want in (("第 1 页", addr_a, A, True),
                                          ("第 2 页", addr_b, B, True),
                                          ("第 3 页（毒页）", addr_c, C, False),
                                          ("第 4 页", addr_d, D, True)):
                s = sc.Scanner(proc, vt)
                s.first_scan(sc.EXACT, val, regions=[region])
                hit = addr in s.addrs
                check(f"{name}：{'命中' if want else '确实读不到（应丢弃）'}",
                      hit is want, f"命中 {s.count} 条")

            # ---------------- 3. 命中不重复（跨块重叠不再重复计数） ----------------
            s3 = sc.Scanner(proc, vt)
            n3 = s3.first_scan(sc.EXACT, D, regions=[region])
            check("精确扫描无重复命中",
                  n3 == len(set(s3.addrs)) == 1, f"{n3} 条命中")

            # 一页放满同一个值 -> 命中数应等于该页槽位数（字节对齐下不重复）
            FILL = 0x0ABC0DEF
            for off in range(0, PAGE, 4):
                ctypes.c_int32.from_address(base + 3 * PAGE + off).value = FILL
            s3b = sc.Scanner(proc, vt)
            n3b = s3b.first_scan(sc.EXACT, FILL, regions=[region])
            uniq3b = len(set(s3b.addrs))
            check("整页同值时命中无重复", uniq3b == n3b == PAGE // 4,
                  f"{n3b} 条 / {uniq3b} 个唯一地址（期望 {PAGE // 4}）")

            # ---------------- 4. 大于扫描 ----------------
            s4 = sc.Scanner(proc, vt)
            n4 = s4.first_scan(sc.GREATER, 0, regions=[region])
            check("大于扫描：可读页的值都在结果里",
                  all(a in s4.addrs for a in (addr_a, addr_b)) and addr_c not in s4.addrs,
                  f"{n4}")

            # ---------------- 5. 未知初始值：只丢毒页 ----------------
            s5 = sc.Scanner(proc, vt)
            cnt = s5.first_scan(sc.UNKNOWN, regions=[region])
            check("未知初始值扫描只丢毒页", cnt == 3 * PAGE // 4,
                  f"记录 {cnt} 个槽位（期望 {3 * PAGE // 4}）")

            # ---------------- 6. 地址表无重复 ----------------
            check("未知初始值扫描无重复地址",
                  len(set(s5.addrs)) == len(s5.addrs), f"{len(s5.addrs)}")

        finally:
            winmem.Process.read = orig_read

        # ---------------- 7. 恢复正常后行为不受影响 ----------------
        s6 = sc.Scanner(proc, vt)
        n6 = s6.first_scan(sc.EXACT, A, regions=[region])
        check("去掉毒页后一切照常", addr_a in s6.addrs and n6 >= 1, f"命中 {n6}")
        s7 = sc.Scanner(proc, vt)
        n7 = s7.first_scan(sc.UNKNOWN, regions=[region])
        check("去掉毒页后未知扫描覆盖全部 4 页", n7 == span // 4, f"记录 {n7}")

    finally:
        k32.VirtualFree(ctypes.c_void_p(base), 0, 0x8000)   # MEM_RELEASE
        proc.close()

    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
