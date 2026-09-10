# -*- coding: utf-8 -*-
"""P7 自测：高 DPI 支持 —— 感知声明、缩放换算、窗口几何夹紧。

不依赖游戏进程，但要建一个真实 Tk 根窗口来验证 `tk scaling` 是否真的生效。
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
import tkinter.font

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ui import scaling as sc                       # noqa: E402
from ui.theme import FONT                          # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def main() -> int:
    # ---------------- 1. DPI 感知声明 ----------------
    awareness = sc.enable_dpi_awareness()
    check("能够声明 DPI 感知", awareness in sc.AWARENESS_LABELS, awareness)
    check("声明结果是可用级别（非 unsupported）",
          awareness != "unsupported" or sc.current_dpi() <= 96,
          f"{awareness} / DPI {sc.current_dpi()}")

    # ---------------- 2. DPI 与工作区 ----------------
    dpi = sc.current_dpi()
    check("DPI 取值合理", 72 <= dpi <= 480, str(dpi))
    wa, ha = sc.work_area()
    check("工作区尺寸合理", wa > 200 and ha > 200, f"{wa}×{ha}")

    # ---------------- 3. 缩放因子换算（下拉框的百分比 = 界面实际倍数） ----------------
    expected = {
        "auto": dpi / 96.0,      # 自动 = 跟随系统
        "100%": 1.0,             # 手动 = 与系统无关，所见即所得
        "125%": 1.25,
        "150%": 1.5,
        2.0: 2.0,
        150: 1.5,                # 写成 150 按百分比理解
    }
    for raw, want in expected.items():
        _auto, _user, got = sc.resolve_factor(raw, dpi)
        check(f"缩放解析 {raw!r} → {got:.3f}", abs(got - want) < 1e-6,
              f"期望 {want:.3f}")

    check("非法值回落到自动", sc.parse_setting("乱写的") == (True, 1.0))
    check("空值回落到自动", sc.parse_setting("") == (True, 1.0))
    check("过大的倍率被夹到 4.0", sc.resolve_factor(500, dpi)[2] == 4.0)
    check("过小的倍率被夹到 0.5", sc.resolve_factor(0.01, dpi)[2] == 0.5)
    check("手动倍率不再乘系统 DPI", sc.resolve_factor("100%", 144)[2] == 1.0,
          "100% 就是 100%")

    # ---------------- 4. 配置值 <-> 界面文字 ----------------
    for raw, text in [("auto", "自动"), ("150%", "150%"), (1.25, "125%"), (2.0, "200%")]:
        check(f"下拉框文字 {raw!r} → {text!r}", sc.setting_text(raw) == text,
              sc.setting_text(raw))
    for text, raw in [("自动", "auto"), ("150%", 1.5), ("175%", 1.75)]:
        check(f"下拉框回写 {text!r} → {raw!r}", sc.setting_value(text) == raw,
              str(sc.setting_value(text)))

    # ---------------- 5. px / pxs 换算 ----------------
    sc.SCALE.dpi = 144
    sc.SCALE.factor = 1.5
    check("px(10) = 15", sc.px(10) == 15, str(sc.px(10)))
    check("px 结果是整数", isinstance(sc.px(7), int), type(sc.px(7)).__name__)
    check("pxs 保留元组结构", sc.pxs(14, 10) == (21, 15), str(sc.pxs(14, 10)))
    check("pxs 支持 4 元组", sc.pxs(10, 8, 10, 10) == (15, 12, 15, 15),
          str(sc.pxs(10, 8, 10, 10)))
    sc.SCALE.factor = 1.0
    check("factor=1 时 px 不改变数值", sc.px(23) == 23, str(sc.px(23)))
    sc.SCALE.factor = 1.5

    # ---------------- 6. 窗口几何夹紧 ----------------
    check("乱写的几何串被拒收", sc.sane_geometry("abc", 1000, 640) is None)
    check("空几何串被拒收", sc.sane_geometry("", 1000, 640) is None)
    big = sc.sane_geometry("9999x9999+9000+9000", 1000, 640)
    w, h = (int(x) for x in big.split("+")[0].split("x"))
    check("超大窗口被夹进工作区", w <= wa and h <= ha, f"{big}")
    pos = big.split("+", 1)[1].split("+")
    check("窗口位置仍在屏内", int(pos[0]) <= wa and int(pos[1]) <= ha, f"{big}")
    tiny = sc.sane_geometry("10x10+0+0", 1000, 640)
    check("过小窗口被抬到最小尺寸", tiny.startswith("1000x640"), tiny)
    plain = sc.sane_geometry("1600x1000", 1000, 640)
    check("只给尺寸时保持尺寸", plain == "1600x1000", str(plain))
    neg = sc.sane_geometry("1600x1000-3000+50", 1000, 640)
    check("跑到屏外的负坐标被拉回", int(neg.split("+")[0].split("x")[0]) == 1600
          and neg.count("+") + neg.count("-") >= 2, neg)

    # ---------------- 7. 默认窗口尺寸 ----------------
    (dw, dh), (mw, mh) = sc.default_geometry()
    check("默认窗口不超出工作区", dw <= wa and dh <= ha, f"{dw}×{dh}（工作区 {wa}×{ha}）")
    check("最小尺寸不大于默认尺寸", mw <= dw and mh <= dh, f"最小 {mw}×{mh}")

    # ---------------- 8. 真实 Tk：scaling 是否真的生效 ----------------
    root = tk.Tk()
    try:
        root.withdraw()
        for raw, want_factor in [("auto", dpi / 96.0), ("100%", 1.0), ("200%", 2.0)]:
            s = sc.apply(root, raw)
            tk_scaling = float(root.tk.call("tk", "scaling"))
            expect_scaling = 96.0 / 72.0 * want_factor
            check(f"apply({raw!r})：tk scaling = {expect_scaling:.3f}",
                  abs(tk_scaling - expect_scaling) < 0.01, f"实测 {tk_scaling:.3f}")
            check(f"apply({raw!r})：factor = {want_factor:.3f}",
                  abs(s.factor - want_factor) < 1e-6, f"实测 {s.factor:.3f}")

        # 字体实际像素高度应该随缩放变大（Tk 的字体按 point 定义，靠 tk scaling 换算）
        sc.apply(root, "100%")
        h_small = tk.font.Font(root=root, family=FONT, size=10).metrics("linespace")
        sc.apply(root, "200%")
        h_big = tk.font.Font(root=root, family=FONT, size=10).metrics("linespace")
        check("倍率翻倍后字体像素高度同步变大", h_big >= h_small * 1.8,
              f"{h_small}px → {h_big}px")
        check("describe() 可读", "DPI" in sc.SCALE.describe(), sc.SCALE.describe())
    finally:
        root.destroy()

    print()
    if fails:
        print("失败项:", ", ".join(fails))
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
