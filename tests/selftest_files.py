# -*- coding: utf-8 -*-
"""P5 自测：_debug.txt 精确改写/备份/还原、存档备份校验、路径探测。

注意：本测试全程在临时目录内操作，不会改动游戏目录与真实存档。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import paths, saves  # noqa: E402
from core.debug_flags import DebugFlags  # noqa: E402

GAME_DIR = Path(os.environ.get("AIC_GAME_DIR") or os.path.dirname(ROOT))

# 这些测试要对着真实游戏跑；不在游戏目录里就直说，别让人对着莫名其妙的报错发呆
if not os.path.isfile(os.path.join(GAME_DIR, "AliceInCradle.exe")):
    print(f"[跳过] 找不到游戏目录：{GAME_DIR}")
    print("       请把本工具放在游戏根目录下（与 AliceInCradle.exe 同级），"
          "或设置环境变量 AIC_GAME_DIR 指向游戏目录。")
    raise SystemExit(2)


fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def test_debug_flags(tmp: Path) -> None:
    print("—— _debug.txt 开关 ——")
    src = paths.debug_txt(GAME_DIR)
    if not src.is_file():
        check("找到游戏 _debug.txt", False, str(src))
        return
    dst = tmp / "_debug.txt"
    shutil.copy2(src, dst)
    original = dst.read_bytes()

    df = DebugFlags(dst)
    vals = df.load()
    check("解析出开关", len(vals) >= 10, f"{len(vals)} 个开关")
    check("DEBUG 开关被识别（含 <> 写法）", "DEBUG" in vals, f"DEBUG={vals.get('DEBUG')}")
    check("mighty / nodamage / allskill 被识别",
          all(k in vals for k in ("mighty", "nodamage", "allskill")))

    entries = df.entries()
    check("面板条目含中文说明",
          any(e.key == "nodamage" and e.desc for e in entries))

    # 修改两个开关
    ok = df.set_many({"nodamage": 1, "allskill": 1})
    check("写入两个开关成功", ok, df.last_error)
    check("备份 _debug.txt.orig.bak 已生成", df.orig_backup.is_file())
    check("原始备份与最初内容完全一致", df.orig_backup.read_bytes() == original)

    reloaded = DebugFlags(dst).load()
    check("重新加载后新值生效",
          reloaded.get("nodamage") == 1 and reloaded.get("allskill") == 1)

    # 除目标行外逐字节一致
    diff = df.diff_summary()
    check("只改动了目标行", len(diff) == 2, f"差异行数={len(diff)}")
    print("      差异内容:")
    for d in diff:
        print("        " + d.replace("\n", "\n        "))

    new_bytes = dst.read_bytes()
    check("文件长度不变（仅替换等长数字）", len(new_bytes) == len(original),
          f"{len(original)} -> {len(new_bytes)}")
    check("行数不变", new_bytes.count(b"\n") == original.count(b"\n"))

    # F7 调试菜单
    df.unlock_f7_menu()
    v2 = DebugFlags(dst).load()
    check("解锁 F7 调试菜单（announce+timestamp=1）",
          v2.get("announce") == 1 and v2.get("timestamp") == 1)

    # 还原
    check("一键还原到最初版本", df.restore("orig"))
    check("还原后与原始字节完全一致", dst.read_bytes() == original)
    check("还原前保存了 .before_restore", (dst.with_name(dst.name + ".before_restore")).is_file())


def test_saves(tmp: Path) -> None:
    print("\n—— 存档备份 ——")
    fake_save = tmp / "savedata_dir"
    fake_save.mkdir()
    (fake_save / "savedata_00.aicsave").write_bytes(b"AIC" * 500)
    (fake_save / "savedata_01.aicsave").write_bytes(b"XYZ" * 300)
    (fake_save / "whole.data").write_bytes(b"\x92V\xab\xf0" + b"\x00" * 20)
    (fake_save / "config.cfg").write_bytes(b"cfg" * 10)
    fake_backup = tmp / "backup"
    fake_backup.mkdir()

    # 让 saves 模块指向临时目录
    saves.save_dir = lambda: fake_save            # type: ignore[assignment]
    saves.save_files = lambda: [                  # type: ignore[assignment]
        p for p in sorted(fake_save.iterdir()) if p.is_file()
    ]
    saves.backup_dir = lambda: fake_backup        # type: ignore[assignment]

    target, msg = saves.create_backup("test")
    check("创建备份成功", target is not None, msg)
    check("manifest 存在", (target / "manifest.json").is_file())
    check("备份内文件数正确", len(list(target.glob("*"))) == 5,
          f"{len(list(target.glob('*')))} 项（4 文件 + manifest）")
    check("sha256 校验通过", saves.verify_backup(target) == [], str(saves.verify_backup(target)))

    infos = saves.list_backups()
    check("能列出备份", len(infos) == 1, infos[0].title if infos else "")

    # 模拟存档被写坏后还原
    (fake_save / "savedata_00.aicsave").write_bytes(b"BROKEN")
    (fake_save / "savedata_01.aicsave").unlink()
    ok, rmsg = saves.restore_backup(target)
    check("还原成功", ok, rmsg)
    check("损坏文件已恢复", (fake_save / "savedata_00.aicsave").read_bytes() == b"AIC" * 500)
    check("被删文件已恢复", (fake_save / "savedata_01.aicsave").is_file())
    check("还原前自动做了安全备份",
          any(i.tag == "prerestore" for i in saves.list_backups()))


def test_paths() -> None:
    print("\n—— 路径探测 ——")
    check("游戏目录可识别", paths.is_game_dir(GAME_DIR), str(GAME_DIR))
    check("主程序存在", paths.game_exe(GAME_DIR).is_file())
    check("_debug.txt 存在", paths.debug_txt(GAME_DIR).is_file())
    sd = paths.save_dir()
    check("存档目录存在", sd.is_dir(), str(sd))
    fs = paths.save_files()
    check("能枚举存档文件", len(fs) >= 3,
          "、".join(f.name for f in fs))

    import time
    t0 = time.time()
    found = paths.find_game_dir(str(GAME_DIR.parent))
    dt = time.time() - t0
    check("显式目录自动定位成功", found is not None and paths.is_game_dir(found),
          f"{found}（{dt:.2f}s）")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="aic_test_") as td:
        tmp = Path(td)
        test_debug_flags(tmp)
        test_saves(tmp)
    test_paths()

    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
