# -*- coding: utf-8 -*-
"""傻瓜式定位：把「精确值首扫 → 再筛选 → 减少了」这套专业流程，包成两步操作。

新手不需要理解字节宽度，也不需要理解「筛选模式」：
    ① 输入游戏里看到的数字 → 工具自动完成首扫
    ② 回游戏让这个数字变化 → 回来点「变小了」或「变大了」（或按 F8 / F9）
    ③ 重复 1~2 次，候选收敛到个位数即成，然后一键锁定 / 存成预设

两个关键设计
------------
1. **方向由用户按的按钮决定**，而不是让用户去选「增加了 / 减少了 / 变化了」——
   按钮上写的就是他刚做过的事，不可能选错。

2. **四种数值宽度同时保留，让「变化」来淘汰**。
   如果只挑「首扫命中最少」的那种宽度，可能挑中一个根本不含真地址的宽度
   （比如金币 137 恰好被 8 字节宽度匹配到别处，命中数更少），用户就会白忙一场。
   所以这里对每种宽度各跑一个扫描器，每次「变化」都同时筛四个，
   留下「还剩候选且候选最少」的那个 —— 宽度猜错也会被自动淘汰掉。

本模块只负责「候选收敛」，界面与锁定在 `ui/tab_onekey.py`。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .scanner import CHANGED, DECREASED, EXACT, INCREASED, VALUE_TYPES, Scanner

# 自动尝试的宽度。
#
# 只扫「4 字节」和「2 字节」这两种主力宽度：全进程一遍要读三四百 MB（实测约 1.5~2 秒），
# 少扫一种就省一秒多。这两种已经覆盖绝大多数情况，包括「数值其实按 64 位存」的场景
# （小数值按 8 字节存时，低 4 字节照样能被 4 字节模式匹配到）。
#
# 「1 字节」和「8 字节」降级为兜底：只有主力宽度一个都没命中时才补扫。
# 原因是它们要么几乎必然命中几十万个（1 字节 = 内存里每 256 个字节就有一个），
# 要么命中的根本不是真地址（8 字节要求后 7 个字节为 0），扫了纯浪费用户的时间。
PRIMARY_TYPES = ("4bytes", "2bytes")
FALLBACK_TYPES = ("byte", "8bytes")

MAX_RESULTS = 200_000          # 单种宽度的候选上限（再多实时筛选就慢了）
DONE_THRESHOLD = 3             # 候选 ≤ 这么多就算找到了


# ---------------------------------------------------------------- 用途预设

@dataclass(frozen=True)
class Purpose:
    key: str
    label: str          # 界面上显示的名字
    what: str           # 「现在游戏里…是多少」里的那个"什么"
    smaller: str        # 让数值变小的操作说明
    bigger: str         # 让数值变大的操作说明
    lock: int           # 「锁定为」输入框的默认值
    slot: str           # 绑定到哪个功能槽位（能被全局热键驱动）
    name: str           # 存成预设时的名字


PURPOSES: dict[str, Purpose] = {
    "money": Purpose(
        "money", "金币", "现在游戏里的金币",
        "去商店花掉一些钱（或者买点东西）", "去捡钱 / 卖东西",
        999999, "add_money", "金币"),
    "item": Purpose(
        "item", "物品数量", "现在这个物品的数量",
        "用掉或者卖掉一个（数量 -1）", "再捡起一个（数量 +1）",
        999, "", "物品数量"),
    "stat": Purpose(
        "stat", "生命 / 魔力等数值", "现在这个数值",
        "挨打掉血 / 放技能耗蓝", "回血 / 喝药",
        9999, "", "自定义数值"),
    "custom": Purpose(
        "custom", "其他数值", "现在这个数值",
        "让它变小", "让它变大",
        999999, "", "自定义数值"),
}


# ---------------------------------------------------------------- 首扫

@dataclass
class Probe:
    """一种数值宽度的候选集合。"""
    key: str
    scanner: Scanner

    @property
    def count(self) -> int:
        return len(self.scanner.addrs)


@dataclass
class LocateReport:
    probes: list[Probe] = field(default_factory=list)
    hits: list[tuple[str, int]] = field(default_factory=list)   # (宽度, 首扫命中数)
    chosen: str = ""
    truncated: bool = False

    @property
    def scanner(self) -> Scanner | None:
        for p in self.probes:
            if p.key == self.chosen:
                return p.scanner
        return None

    @property
    def count(self) -> int:
        sc = self.scanner
        return len(sc.addrs) if sc else 0

    def best(self) -> Probe | None:
        """候选最少但仍有候选的那个宽度。"""
        alive = [p for p in self.probes if p.count > 0]
        return min(alive, key=lambda p: p.count) if alive else None

    def describe_hits(self) -> str:
        return "、".join(f"{VALUE_TYPES[k].label} {n}" for k, n in self.hits)


def locate_initial(proc, value, *,
                   include_readonly: bool = False,
                   include_mapped: bool = False,
                   max_results: int = MAX_RESULTS,
                   progress=None,
                   cancelled=None) -> LocateReport:
    """对每种能表示该数值的宽度各扫一遍，全部保留下来交给后续收敛。

    主力宽度扫完一个都没命中时，再补扫兜底宽度（1 字节 / 8 字节）。
    全都 0 命中时 `probes` 为空，由界面提示用户检查数字是否看错。
    """
    def packable(key: str) -> bool:
        try:
            VALUE_TYPES[key].pack(value)       # 超出该宽度能表示的范围就跳过
            return True
        except Exception:
            return False

    primary = [k for k in PRIMARY_TYPES if packable(k)]
    fallback = [k for k in FALLBACK_TYPES if packable(k)]
    if not primary and not fallback:
        return LocateReport()

    report = LocateReport()

    def sweep(types: list[str], base: float, span: float) -> None:
        for i, key in enumerate(types):
            if cancelled and cancelled():
                return
            probe = Scanner(proc, VALUE_TYPES[key], include_readonly, include_mapped,
                            max_results=max_results)
            n = probe.first_scan(
                EXACT, value,
                progress=(lambda f, t, i=i: progress(base + span * (i + f) / len(types), t))
                if progress else None,
                cancelled=cancelled)
            report.hits.append((key, n))
            report.truncated = report.truncated or probe.truncated
            if n:
                report.probes.append(Probe(key, probe))

    if primary:
        sweep(primary, 0.0, 0.85 if fallback else 1.0)
        if not report.probes and fallback:
            sweep(fallback, 0.85, 0.15)      # 主力全落空，补扫兜底宽度
    else:
        sweep(fallback, 0.0, 1.0)

    best = report.best()
    report.chosen = best.key if best else ""
    return report


# ---------------------------------------------------------------- 收敛向导

class Wizard:
    """一步步缩小候选范围。每次用户说「变小了 / 变大了」就把所有宽度同时筛一轮。"""

    def __init__(self, proc, *, include_readonly: bool = False,
                 include_mapped: bool = False) -> None:
        self.proc = proc
        self.include_readonly = include_readonly
        self.include_mapped = include_mapped
        self.report: LocateReport | None = None
        self.rounds = 0
        self.started_value = None

    # ---------------------------------------- 生命周期

    def begin(self, value, progress=None, cancelled=None) -> LocateReport:
        self.rounds = 0
        self.started_value = value
        self.report = locate_initial(
            self.proc, value,
            include_readonly=self.include_readonly,
            include_mapped=self.include_mapped,
            progress=progress, cancelled=cancelled)
        return self.report

    def reset(self) -> None:
        self.report = None
        self.rounds = 0
        self.started_value = None

    # ---------------------------------------- 状态

    @property
    def active(self) -> bool:
        return self.report is not None and self.report.chosen != ""

    @property
    def count(self) -> int:
        return self.report.count if self.report else 0

    @property
    def scanner(self) -> Scanner | None:
        return self.report.scanner if self.report else None

    @property
    def solved(self) -> bool:
        return self.active and 0 < self.count <= DONE_THRESHOLD

    def summary(self) -> str:
        if self.report is None:
            return "还没开始"
        if not self.report.chosen:
            return f"没找到这个数字（各宽度命中：{self.report.describe_hits() or '无'}）"
        vt = self.report.scanner.vt
        extra = f"，第 {self.rounds} 次缩小后" if self.rounds else ""
        return f"按 {vt.label} 统计，现在还剩 {self.count} 个候选{extra}"

    # ---------------------------------------- 缩小范围

    def narrow(self, bigger: bool) -> int:
        """用户报告数值变化方向：所有宽度同时筛，留下最有希望的那个。"""
        return self._narrow(INCREASED if bigger else DECREASED)

    def narrow_any(self) -> int:
        """方向不明时只要求「变了」。"""
        return self._narrow(CHANGED)

    def _narrow(self, mode: str) -> int:
        if not (self.report and self.report.probes):
            return 0
        for probe in self.report.probes:
            probe.scanner.next_scan(mode)
        # 候选归零的宽度直接淘汰，剩下的里选候选最少的
        self.report.probes = [p for p in self.report.probes if p.count > 0]
        best = self.report.best()
        self.report.chosen = best.key if best else ""
        self.rounds += 1
        return self.count

    # ---------------------------------------- 结果

    def candidates(self, limit: int = 100) -> list[tuple[int, object]]:
        sc = self.scanner
        return sc.read_snapshot(limit=limit) if sc else []

    def targets(self, limit: int = 8) -> list[int]:
        """当前所有候选的地址。

        同一份数值在内存里往往有多份拷贝（例如显示用 + 逻辑用），它们永远同值同变，
        用户没法也不该去区分 —— 所以锁定时把这些一起锁上。
        """
        return [a for a, _v in self.candidates(limit=limit)]

    def all_same(self) -> bool:
        """剩下的候选是不是「永远同值」（说明它们是同一个数值的多份拷贝）。"""
        vals = [v for _a, v in self.candidates(limit=DONE_THRESHOLD + 1)]
        if len(vals) < 2:
            return True
        return len({str(v) for v in vals}) == 1

    def best(self) -> tuple[int, object] | None:
        """只剩一个候选时直接给出，省得用户还要在表里挑。"""
        rows = self.candidates(limit=DONE_THRESHOLD + 1)
        return rows[0] if len(rows) == 1 else None

    def current_of(self, addr: int):
        sc = self.scanner
        return sc.read_one(addr) if sc else None
