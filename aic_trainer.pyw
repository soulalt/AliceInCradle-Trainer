# -*- coding: utf-8 -*-
"""爱丽丝的摇篮 修改器 —— 程序入口。

双击「启动修改器.bat」或直接运行本文件。
"""

from __future__ import annotations

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _fatal(exc: BaseException) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        with open(os.path.join(HERE, "logs", "crash.log"), "a", encoding="utf-8") as fh:
            fh.write(detail + "\n")
    except OSError:
        pass
    try:
        import tkinter.messagebox as mb
        mb.showerror("修改器启动失败",
                     f"{exc}\n\n详细信息已写入 logs/crash.log")
    except Exception:
        sys.stderr.write(detail)


def main() -> int:
    try:
        os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
        from ui.main_window import main as run
        return run()
    except BaseException as exc:      # noqa: BLE001 - 兜底展示，避免静默退出
        _fatal(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
