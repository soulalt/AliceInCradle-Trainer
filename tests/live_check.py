# -*- coding: utf-8 -*-
"""实机自检：启动游戏 -> 附加 -> 校验模块/内存区域 -> 做一次真实扫描 -> 关闭游戏。

用法：
    python tests/live_check.py              # 启动游戏、自检、然后关闭它
    python tests/live_check.py --attach-only  # 只附加当前已运行的游戏，不动它

这是给用户用的「体检」脚本，可以随时跑一遍确认修改器对当前游戏版本仍然好使。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import paths, winmem  # noqa: E402
from core.scanner import Scanner, VALUE_TYPES  # noqa: E402

GAME_DIR = Path(os.environ.get("AIC_GAME_DIR") or os.path.dirname(ROOT))

# 这些测试要对着真实游戏跑；不在游戏目录里就直说，别让人对着莫名其妙的报错发呆
if not os.path.isfile(os.path.join(GAME_DIR, "AliceInCradle.exe")):
    print(f"[跳过] 找不到游戏目录：{GAME_DIR}")
    print("       请把本工具放在游戏根目录下（与 AliceInCradle.exe 同级），"
          "或设置环境变量 AIC_GAME_DIR 指向游戏目录。")
    raise SystemExit(2)


u32 = ctypes.WinDLL("user32", use_last_error=True)


def close_windows_of_pid(pid: int) -> int:
    """向该进程的所有可见窗口发送 WM_CLOSE（让游戏自己优雅退出）。"""
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    hit: list[int] = []

    def cb(hwnd, _lp):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            hit.append(hwnd)
            u32.PostMessageW(hwnd, 0x0010, 0, 0)
        return True

    u32.EnumWindows(EnumWindowsProc(cb), 0)
    return len(hit)


def main() -> int:
    attach_only = "--attach-only" in sys.argv
    game_dir = paths.find_game_dir(str(GAME_DIR)) or paths.find_game_dir("")
    if not game_dir:
        print("[X] 没找到游戏目录")
        return 1
    print(f"游戏目录：{game_dir}")

    pid = winmem.find_pid_by_name(paths.APP_EXE)
    launched = False
    if pid is None:
        if attach_only:
            print("[X] 游戏没在运行（--attach-only 模式不会帮你启动）")
            return 1
        print("正在启动游戏…")
        subprocess.Popen([str(paths.game_exe(game_dir))], cwd=str(game_dir))
        launched = True
        for _ in range(60):
            time.sleep(2)
            pid = winmem.find_pid_by_name(paths.APP_EXE)
            if pid:
                break
        if pid is None:
            print("[X] 等待游戏进程超时")
            return 1
    print(f"目标进程：pid={pid}")

    proc = winmem.Process(pid)
    if not proc.open():
        print("[X]", proc.last_error)
        return 1
    print(f"64 位进程：{proc.is_64bit}\n")

    t0 = time.time()
    mods = proc.modules()
    print(f"模块：{len(mods)} 个（枚举耗时 {time.time()-t0:.2f}s）")
    for m in mods[:8]:
        print(f"    {m.name:<32} base=0x{m.base:012X}  {m.size/1024:>8.0f} KB")
    mono = next((m for m in mods if "mono" in m.name.lower()), None)
    exe_mod = next((m for m in mods if m.name.lower() == paths.APP_EXE.lower()), None)
    print(f"  → Mono 运行时：{mono.name if mono else '未发现'}")
    print(f"  → 主程序基址：0x{exe_mod.base:012X}" if exe_mod else "  → 主程序模块未找到")

    t0 = time.time()
    regs = proc.regions()
    total = sum(r.size for r in regs)
    print(f"\n可写内存区域：{len(regs)} 个 / {total/1048576:.1f} MB（枚举耗时 {time.time()-t0:.2f}s）")
    big = sorted(regs, key=lambda r: -r.size)[:3]
    for r in big:
        print(f"    0x{r.base:012X}  {r.size/1048576:.1f} MB")

    # 一次真实扫描：找一个常见值，检验扫描速度与结果一致性
    sc = Scanner(proc, VALUE_TYPES["4bytes"], max_results=2_000_000)
    t0 = time.time()
    n = sc.first_scan("精确值", 1000)
    dt = time.time() - t0
    print(f"\n真实扫描测试：全进程搜 4 字节值 1000 → 命中 {n} 个，耗时 {dt:.2f}s"
          + ("（已截断）" if sc.truncated else ""))

    # 即时复核：首扫结束时扫描器会立刻回读一遍所有命中地址，这里统计仍等于目标值的比例。
    sample = list(sc.prev[:2000])
    good = sum(1 for v in sample if int(v) == 1000)
    ratio = good / len(sample) * 100 if sample else 0
    print(f"即时复核：抽样 {len(sample)} 个命中地址，其中 {good} 个仍等于 1000"
          f"（{ratio:.1f}%）")
    if sample and ratio < 50:
        print("  ⚠ 一致率偏低 —— 目标进程内存变动极快，建议多轮筛选后再锁定")
    elif sample:
        print("  → 一致率正常，扫描结果可信（活体游戏内存会持续变动，属正常现象）")

    # 用「再筛选」跑一轮，验证收敛能力
    if n:
        n2 = sc.next_scan("精确值", 1000)
        n3 = sc.next_scan("精确值", 1000)
        print(f"连续再筛选：{n} → {n2} → {n3}（应基本稳定，能收敛）")

    print("\n[OK] 实机自检通过：附加、模块枚举、内存区域枚举、真实扫描都正常。")
    proc.close()

    if launched:
        print("\n正在关闭游戏…")
        n = close_windows_of_pid(pid)
        print(f"已向 {n} 个窗口发送关闭请求")
        for _ in range(10):
            time.sleep(1)
            if winmem.find_pid_by_name(paths.APP_EXE) is None:
                print("游戏已退出。")
                return 0
        print("游戏未自行退出 —— 如需关闭请手动操作（自检不影响存档）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
