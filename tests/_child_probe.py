# -*- coding: utf-8 -*-
"""辅助进程：分配一块已知缓冲区，打印地址后持续回报数值，用于跨进程验证。"""

from __future__ import annotations

import ctypes
import sys
import time

buf = (ctypes.c_int32 * 64)()
for i in range(64):
    buf[i] = i + 1
buf[5] = 0x1A2B3C4D

print(hex(ctypes.addressof(buf) + 5 * 4), flush=True)

deadline = time.time() + 30
while time.time() < deadline:
    print(int(buf[5]), flush=True)
    time.sleep(0.2)
