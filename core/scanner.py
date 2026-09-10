# -*- coding: utf-8 -*-
"""数值扫描引擎（Cheat Engine 式）。

首扫用「分块 RPM + bytes.find」在 C 层匹配字节模式，速度接近 CE 的快速扫描；
再筛选只在候选地址表上做，并有进度回调与取消支持。
"""

from __future__ import annotations

import array
import struct
from dataclasses import dataclass
from typing import Callable, Iterable

from .winmem import Process, Region

CHUNK = 8 << 20  # 每次 ReadProcessMemory 8MB

Progress = Callable[[float, str], None]
Cancelled = Callable[[], bool]


# ---------------------------------------------------------------- 数值类型

@dataclass(frozen=True)
class ValueType:
    key: str
    label: str
    code: str          # array 模块的类型码
    fmt: str           # struct 打包格式（小端，有符号）
    size: int
    is_float: bool

    def pack(self, value) -> bytes:
        """打包为字节。整型类型会自动把浮点输入取整（锁定表统一用 float 存值）。

        有符号放不下时自动改用无符号表示（同一数值的字节序与显示无关）。
        """
        if not self.is_float and isinstance(value, float):
            value = int(round(value))
        try:
            return struct.pack(self.fmt, value)
        except struct.error:
            unsigned = {"<b": "<B", "<h": "<H", "<i": "<I", "<q": "<Q"}.get(self.fmt)
            if unsigned is None:      # float / double 溢出无法用无符号补救
                raise
            return struct.pack(unsigned, value)

    def unpack(self, raw: bytes, offset: int = 0):
        return struct.unpack_from(self.fmt, raw, offset)[0]

    def unpack_unsigned(self, raw: bytes, offset: int = 0):
        fmt = self.fmt[:-1] + {"b": "B", "h": "H", "i": "I", "q": "Q"}[self.fmt[-1]]
        return struct.unpack_from(fmt, raw, offset)[0]


VALUE_TYPES: dict[str, ValueType] = {
    "byte": ValueType("byte", "1 字节", "b", "<b", 1, False),
    "2bytes": ValueType("2bytes", "2 字节", "h", "<h", 2, False),
    "4bytes": ValueType("4bytes", "4 字节", "i", "<i", 4, False),
    "8bytes": ValueType("8bytes", "8 字节", "q", "<q", 8, False),
    "float": ValueType("float", "浮点 (float)", "f", "<f", 4, True),
    "double": ValueType("double", "双精度 (double)", "d", "<d", 8, True),
}
TYPE_ORDER = ["byte", "2bytes", "4bytes", "8bytes", "float", "double"]


def fmt_value(vt: ValueType, value) -> str:
    if value is None:
        return "—"
    if vt.is_float:
        return f"{value:.4g}" if abs(value) >= 1e-4 or value == 0 else f"{value:.6g}"
    return str(value)


def parse_value(text: str, vt: ValueType):
    text = (text or "").strip()
    if not text:
        raise ValueError("请输入数值")
    try:
        if vt.is_float:
            return float(text)
        # 支持 0x 十六进制
        if text.lower().startswith(("0x", "-0x")):
            return int(text, 16)
        return int(text, 10)
    except ValueError as exc:
        raise ValueError(f"无法解析数值：{text!r}") from exc


# ---------------------------------------------------------------- 扫描模式

EXACT = "精确值"
GREATER = "大于"
LESS = "小于"
BETWEEN = "介于两者之间"
UNKNOWN = "未知初始值"
CHANGED = "变化了"
UNCHANGED = "未变化"
INCREASED = "增加了"
DECREASED = "减少了"

FIRST_MODES = [EXACT, GREATER, LESS, BETWEEN, UNKNOWN]
NEXT_MODES = [EXACT, GREATER, LESS, BETWEEN, CHANGED, UNCHANGED, INCREASED, DECREASED]


# ---------------------------------------------------------------- 扫描器

class Scanner:
    def __init__(
        self,
        proc: Process,
        vtype: ValueType,
        include_readonly: bool = False,
        include_mapped: bool = False,
        max_results: int = 4_000_000,
    ) -> None:
        self.proc = proc
        self.vt = vtype
        self.include_readonly = include_readonly
        self.include_mapped = include_mapped
        self.max_results = max_results

        self.addrs = array.array("Q")           # 候选地址
        self.prev = array.array(vtype.code)     # 上一轮数值（与类型同码，便于整块扩展）
        self.truncated = False

    # -------------------------------------------------- 状态

    @property
    def count(self) -> int:
        return len(self.addrs)

    def set_type(self, vtype: ValueType) -> None:
        self.vt = vtype
        self.clear()

    def clear(self) -> None:
        self.addrs = array.array("Q")
        self.prev = array.array(self.vt.code)
        self.truncated = False

    def regions(self) -> list[Region]:
        return self.proc.regions(
            include_readonly=self.include_readonly,
            include_mapped=self.include_mapped,
        )

    # -------------------------------------------------- 首扫：精确/范围

    def first_scan(
        self,
        mode: str,
        value=None,
        value2=None,
        regions: list[Region] | None = None,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
        allowed: Iterable[Region] | None = None,
    ) -> int:
        if mode == UNKNOWN:
            return self._first_unknown(regions, progress, cancelled, allowed)
        if mode not in FIRST_MODES:
            raise ValueError(f"不支持的首扫方式：{mode}")

        regions = self._resolve(regions, allowed)
        self.clear()
        found: list[int] = []

        for i, r in enumerate(regions):
            if cancelled and cancelled():
                break
            if progress:
                progress(i / max(1, len(regions)),
                         f"扫描区域 {i+1}/{len(regions)}  已命中 {self.count + len(found)}")
            found.extend(self._scan_region(r, mode, value, value2, cancelled))
            if self.count + len(found) >= self.max_results:
                self.truncated = True
                break

        if self.truncated and len(found) > self.max_results:
            del found[self.max_results:]

        self.addrs = array.array("Q", found)
        self.prev = self._current_values(found)
        return len(self.addrs)

    def _resolve(self, regions, allowed) -> list[Region]:
        if regions is not None:
            return regions
        if allowed is not None:
            return list(allowed)
        return self.regions()

    def _scan_region(self, r: Region, mode, value, value2, cancelled) -> list[int]:
        vt = self.vt
        size = vt.size
        hits: list[int] = []
        limit = self.max_results

        if mode == EXACT:
            pattern = vt.pack(value)
            step = len(pattern)
            pos = r.base
            while pos < r.end:
                n = min(CHUNK, r.end - pos)
                tail = min(step - 1, r.end - (pos + n))   # 跨块重叠，防止漏掉骑缝值
                for paddr, pdata in self.proc.read_pieces(pos, n + tail):
                    if self._find_pattern(pdata, paddr, pattern, hits, limit, own=n):
                        return hits
                pos += max(n, 1)
                if cancelled and cancelled():
                    break
            return hits

        # 范围扫描：逐槽解包（较慢，但首扫一般够用）
        pos = r.base
        while pos < r.end:
            n = min(CHUNK, r.end - pos)
            for paddr, data in self.proc.read_pieces(pos, n):
                skip = (pos - paddr) % size          # 片段起点可能不在槽位边界上
                usable = ((len(data) - skip) // size) * size
                if usable <= 0:
                    continue
                arr = array.array(vt.code)
                arr.frombytes(data[skip: skip + usable])
                start = paddr + skip
                for i, v in enumerate(arr):
                    if mode == GREATER and v > value:
                        hits.append(start + i * size)
                    elif mode == LESS and v < value:
                        hits.append(start + i * size)
                    elif mode == BETWEEN and value <= v <= value2:
                        hits.append(start + i * size)
                    if len(hits) >= limit:
                        return hits
            pos += max(n, 1)
            if cancelled and cancelled():
                break
        return hits

    @staticmethod
    def _find_pattern(data: bytes, base_addr: int, pattern: bytes,
                      hits: list[int], limit: int, own: int | None = None) -> bool:
        """在本块数据里找 pattern。`own` 限定本块「拥有」的字节数：

        末尾为防跨块漏匹配多读了 step-1 字节，但那几个字节归下一块管，
        在这里收下会造成**同一条命中被记录两次**，所以按 own 截断。
        """
        end = len(data) if own is None else min(own, len(data))
        idx = data.find(pattern)
        while idx != -1 and idx < end:
            hits.append(base_addr + idx)
            if len(hits) >= limit:
                return True
            idx = data.find(pattern, idx + 1)
        return len(hits) >= limit

    # -------------------------------------------------- 首扫：未知初始值

    def _first_unknown(self, regions, progress, cancelled, allowed) -> int:
        regions = self._resolve(regions, allowed)
        self.clear()
        vt = self.vt
        size = vt.size
        addrs = array.array("Q")
        vals = array.array(vt.code)

        for i, r in enumerate(regions):
            if cancelled and cancelled():
                break
            if progress:
                progress(i / max(1, len(regions)), f"记录初始值 {i+1}/{len(regions)}")
            pos = r.base
            while pos < r.end:
                n = min(CHUNK, r.end - pos)
                for paddr, data in self.proc.read_pieces(pos, n):
                    skip = (pos - paddr) % size
                    usable = ((len(data) - skip) // size) * size
                    if usable <= 0:
                        continue
                    arr = array.array(vt.code)
                    arr.frombytes(data[skip: skip + usable])
                    start = paddr + skip
                    addrs.extend(range(start, start + len(arr) * size, size))
                    vals.extend(arr)
                    if len(addrs) >= self.max_results:
                        self.truncated = True
                        break
                pos += max(n, 1)
                if self.truncated or (cancelled and cancelled()):
                    break
            if self.truncated:
                break

        if self.truncated:
            del addrs[self.max_results:]
            del vals[self.max_results:]

        self.addrs = addrs
        self.prev = vals
        return len(self.addrs)

    # -------------------------------------------------- 再筛选

    def next_scan(
        self,
        mode: str,
        value=None,
        value2=None,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> int:
        if mode not in NEXT_MODES:
            raise ValueError(f"不支持的筛选方式：{mode}")
        if self.count == 0:
            return 0

        vt = self.vt
        size = vt.size
        addrs = self.addrs
        prev = self.prev

        keep_a = array.array("Q")
        keep_v = array.array(vt.code)
        blob = self.proc.read_many([(a, size) for a in addrs], max_span=1 << 21)

        total = len(addrs)
        report_every = max(1, total // 200)

        for i in range(total):
            a = addrs[i]
            raw = blob.get(a)
            if raw is None:
                continue
            cur = vt.unpack(raw)
            ok = False
            if mode == EXACT:
                ok = raw == self.vt.pack(value)
            elif mode == GREATER:
                ok = cur > value
            elif mode == LESS:
                ok = cur < value
            elif mode == BETWEEN:
                ok = value <= cur <= value2
            elif mode == CHANGED:
                ok = cur != prev[i]
            elif mode == UNCHANGED:
                ok = cur == prev[i]
            elif mode == INCREASED:
                ok = cur > prev[i]
            elif mode == DECREASED:
                ok = cur < prev[i]
            if ok:
                keep_a.append(a)
                keep_v.append(cur)
            if progress and i % report_every == 0:
                progress(i / total, f"筛选 {i}/{total}  保留 {len(keep_a)}")
                if cancelled and cancelled():
                    break

        self.addrs = keep_a
        self.prev = keep_v
        return len(self.addrs)

    # -------------------------------------------------- 读取/写入

    def _current_values(self, addrs: Iterable[int]) -> array.array:
        """把一批地址的当前值读成与类型同码的紧凑数组。"""
        vt = self.vt
        addrs = list(addrs)
        blob = self.proc.read_many([(a, vt.size) for a in addrs], max_span=1 << 21)
        out = array.array(vt.code)
        for a in addrs:
            raw = blob.get(a)
            out.append(vt.unpack(raw) if raw is not None else 0)
        return out

    def read_one(self, addr: int):
        raw = self.proc.read(addr, self.vt.size)
        if raw is None:
            return None
        return self.vt.unpack(raw)

    def read_snapshot(self, limit: int = 200_000) -> list[tuple[int, object]]:
        """返回 [(addr, value)]，供结果表显示。"""
        addrs = self.addrs[:limit]
        size = self.vt.size
        blob = self.proc.read_many([(a, size) for a in addrs], max_span=1 << 21)
        out: list[tuple[int, object]] = []
        for a in addrs:
            raw = blob.get(a)
            out.append((a, self.vt.unpack(raw) if raw is not None else None))
        return out

    def write(self, addr: int, value) -> bool:
        return self.proc.write(addr, self.vt.pack(value))

    # -------------------------------------------------- 邻域浏览

    def browse(self, addr: int, span: int = 512) -> list[tuple[int, object]]:
        """列出 [addr-span, addr+span) 内按类型对齐的所有候选值，用于一次定位相邻字段。"""
        vt = self.vt
        size = vt.size
        step = size if size > 1 else 1
        base = (addr - span)
        base -= base % step
        data = self.proc.read(base, span * 2)
        if not data:
            return []
        out: list[tuple[int, object]] = []
        usable = (len(data) // step) * step if vt.size == 1 else (len(data) // size) * size
        for off in range(0, usable, step):
            try:
                out.append((base + off, vt.unpack(data, off)))
            except struct.error:
                break
        return out
