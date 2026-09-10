# -*- coding: utf-8 -*-
"""P1 自测：winmem 是否能枚举模块/区域，并读写自身进程内存。"""

from __future__ import annotations

import ctypes
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import winmem  # noqa: E402


def main() -> int:
    fails = []

    def check(name: str, cond: bool, extra: str = "") -> None:
        print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
        if not cond:
            fails.append(name)

    pid = os.getpid()
    print(f"目标进程: 自身 pid={pid}\n")

    # ---- 进程枚举 ----
    procs = winmem.list_processes()
    check("进程枚举非空", len(procs) > 0, f"共 {len(procs)} 个进程")
    check(
        "能按名字找到自身",
        winmem.find_pid_by_name("python.exe") is not None
        or any(p == pid for p, _ in procs),
    )

    p = winmem.Process(pid)
    ok = p.open()
    check("OpenProcess 打开自身", ok, p.last_error)
    if not ok:
        return 1
    print(f"      目标是否 64 位: {p.is_64bit}")

    # ---- 模块枚举 ----
    mods = p.modules()
    check("模块枚举非空", len(mods) > 0, f"共 {len(mods)} 个模块")
    for m in mods[:5]:
        print(f"      {m.name:<28} base=0x{m.base:012X} size={m.size/1024:.0f}KB")

    # ---- 区域枚举 ----
    regs = p.regions()
    total = sum(r.size for r in regs)
    check("可写区域枚举非空", len(regs) > 0, f"{len(regs)} 个区域 / {total/1048576:.1f} MB")

    # ---- 读写 ----
    holder = ctypes.c_uint32(0xDEADBEEF)
    addr = ctypes.addressof(holder)
    raw = p.read(addr, 4)
    check("ReadProcessMemory 读到已知值", raw == struct.pack("<I", 0xDEADBEEF),
          f"addr=0x{addr:X} 实际={raw.hex() if raw else None}")

    new = struct.pack("<I", 0x12345678)
    check("WriteProcessMemory 写入成功", p.write(addr, new))
    check("写后落值正确", holder.value == 0x12345678, f"回读 {holder.value:#x}")

    # ---- 批量读 ----
    probe = (ctypes.c_uint32 * 4)(11, 22, 33, 44)
    base = ctypes.addressof(probe)
    items = [(base + i * 4, 4) for i in range(4)] + [(addr, 4)]
    got = p.read_many(items)
    expect = [
        struct.pack("<I", 11), struct.pack("<I", 22),
        struct.pack("<I", 33), struct.pack("<I", 44), new,
    ]
    check("read_many 批量读正确", all(got.get(a) == e for (a, _), e in zip(items, expect)),
          f"命中 {len(got)}/{len(items)}")

    # ---- 指针读 ----
    target = ctypes.c_uint64(0x1122334455667788)
    ptr = ctypes.c_uint64(ctypes.addressof(target))
    val = p.read_ptr(ctypes.addressof(ptr))
    check("read_ptr 指针解引用", val == ctypes.addressof(target),
          f"得到 0x{val:X}" if val else "None")

    # ---- 存活判断 ----
    check("alive() 判定为存活", p.alive())

    p.close()

    # ---- 「进程是否已经铺开」判定（自动连接要等游戏加载完才附加）----
    check("process_ready(自身进程) 为真",
          winmem.process_ready(os.getpid(), min_writable=1 << 20))
    check("process_ready 对无效 PID 为假", not winmem.process_ready(0x7FFFFF0))
    check("process_ready 阈值可调（把门槛抬到天上就该为假）",
          not winmem.process_ready(os.getpid(), min_writable=1 << 60))

    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
