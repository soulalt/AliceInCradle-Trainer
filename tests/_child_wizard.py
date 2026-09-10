# -*- coding: utf-8 -*-
"""辅助进程：一块可被远程改动的内存，用来验证「一键」页的自动收敛流程。

刻意把 4096 个槽位**全部填成同一个数字**（默认 137），并再多处重复，
这样精确首扫会命中一大堆地址 —— 只有靠「数值变化」才能把真正的那一个挑出来，
正是向导要解决的情形。

协议（stdout 一行地址，之后按行响应 stdin 命令）：
    set <n>   把目标值设为 n
    get       打印当前值
    quit      退出
"""

from __future__ import annotations

import ctypes
import sys
import time

SLOTS = 4096
DUP = 137                      # 到处都是这个值，逼着向导不能只靠首扫
TARGET_INDEX = 2048

buf = (ctypes.c_int32 * SLOTS)()
for i in range(SLOTS):
    buf[i] = DUP

target_addr = ctypes.addressof(buf) + TARGET_INDEX * 4
print(hex(target_addr), flush=True)
print(f"ready {buf[TARGET_INDEX]}", flush=True)


def _pump_once() -> bool:
    """非阻塞地读一行命令；没有命令就返回 True 继续。"""
    line = sys.stdin.readline()
    if not line:
        return False
    cmd = line.strip().split()
    if not cmd:
        return True
    if cmd[0] == "quit":
        return False
    if cmd[0] == "set" and len(cmd) > 1:
        ctypes.c_int32.from_address(target_addr).value = int(cmd[1])
        print(f"ok {buf[TARGET_INDEX]}", flush=True)
    elif cmd[0] == "get":
        print(f"value {buf[TARGET_INDEX]}", flush=True)
    return True


deadline = time.time() + 120
while time.time() < deadline:
    if not _pump_once():
        break
