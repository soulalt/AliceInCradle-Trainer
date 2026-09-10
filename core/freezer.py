# -*- coding: utf-8 -*-
"""锁定（freeze）与监视：单个后台线程按固定周期回写锁定值、刷新监视值。

线程安全：所有公开方法都在 self._lock 内操作；UI 只读 snapshot()。
地址来源支持「直接地址」与「模块基址 + 偏移链」，后者可跨重启复用。
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

from .scanner import ValueType
from .winmem import Process

INTERVAL = 0.1          # 100ms 一个周期
MODULE_CACHE_TTL = 2.0

_TARGET_RE = re.compile(
    r"^(?P<mod>[^+\s,]+)\s*(?P<offs>(?:[+,\s]\s*(?:0[xX][0-9a-fA-F]+|\d+))*)$"
)


def parse_target(text: str) -> Target:
    """解析用户输入的地址表达式。

    '0x1F3A2B40'                     -> 直接地址
    'AliceInCradle.exe+0x10+0x28'    -> 模块基址 + 二级偏移（抗重启）
    'mono-2.0-bdwgc.dll+0x10,0x28'   -> 同上，逗号也支持
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("地址为空")
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
        return Target(kind="direct", addr=int(text, 16))
    if re.fullmatch(r"\d+", text):
        return Target(kind="direct", addr=int(text, 10))

    m = _TARGET_RE.match(text)
    if not m:
        raise ValueError(f"无法解析地址表达式：{text}")
    module = m.group("mod")
    offsets = [int(x, 0) for x in re.findall(r"0[xX][0-9a-fA-F]+|\d+", m.group("offs") or "")]
    if not offsets:
        raise ValueError("指针链至少要有一个偏移")
    return Target(kind="pointer", module=module, offsets=offsets)


@dataclass
class Target:
    """地址解析策略。"""

    kind: str = "direct"          # direct | pointer
    addr: int = 0
    module: str = ""
    offsets: list[int] = field(default_factory=list)

    def resolve(self, ctx: "_Ctx") -> int | None:
        if self.kind == "direct":
            return self.addr or None
        base = ctx.module_base(self.module)
        if not base:
            return None
        cur = base + (self.offsets[0] if self.offsets else 0)
        for off in self.offsets[1:]:
            ptr = ctx.proc.read_ptr(cur)
            if not ptr:
                return None
            cur = ptr + off
        return cur

    def describe(self) -> str:
        if self.kind == "direct":
            return f"0x{self.addr:X}"
        chain = "".join(f"+0x{o:X}" for o in self.offsets)
        return f"{self.module}{chain}"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "addr": self.addr,
                "module": self.module, "offsets": list(self.offsets)}

    @staticmethod
    def from_dict(d: dict) -> "Target":
        return Target(
            kind=d.get("kind", "direct"),
            addr=int(d.get("addr", 0) or 0),
            module=d.get("module", "") or "",
            offsets=[int(x) for x in d.get("offsets", [])],
        )


class _Ctx:
    def __init__(self, proc: Process) -> None:
        self.proc = proc
        self._mods: dict[str, int] = {}
        self._stamp = 0.0

    def module_base(self, name: str) -> int | None:
        now = time.time()
        if now - self._stamp > MODULE_CACHE_TTL:
            self._mods = {m.name.lower(): m.base for m in self.proc.modules()}
            self._stamp = now
        return self._mods.get(name.lower())


@dataclass
class LockEntry:
    uid: int
    label: str
    target: Target
    vtype: ValueType
    value: float
    enabled: bool = True
    note: str = ""
    slot: str = ""          # 功能槽位名（与预设/热键联动，如 invincible）
    writes: int = 0
    last_error: str = ""

    def to_dict(self) -> dict:
        return {
            "uid": self.uid, "label": self.label, "target": self.target.to_dict(),
            "type": self.vtype.key, "value": self.value, "enabled": self.enabled,
            "note": self.note, "slot": self.slot,
        }


@dataclass
class MonitorEntry:
    uid: int
    label: str
    target: Target
    vtype: ValueType
    value: object = None
    prev: object = None

    def to_dict(self) -> dict:
        return {"uid": self.uid, "label": self.label, "target": self.target.to_dict(),
                "type": self.vtype.key, "note": ""}


class Freezer:
    """锁定 + 监视的单一后台线程。"""

    def __init__(self, proc: Process | None = None, interval: float = INTERVAL) -> None:
        self.proc = proc
        self.interval = interval
        self.locks: dict[int, LockEntry] = {}
        self.monitors: dict[int, MonitorEntry] = {}
        self._lock = threading.RLock()
        self._ctx: _Ctx | None = _Ctx(proc) if proc else None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._next_uid = 1
        self.last_tick = 0.0
        self.ticks = 0

    # -------------------------------------------------- 生命周期

    def set_process(self, proc: Process | None) -> None:
        with self._lock:
            self.proc = proc
            self._ctx = _Ctx(proc) if proc else None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="freezer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.0)
        self._thread = None

    # -------------------------------------------------- 锁定项

    def new_uid(self) -> int:
        with self._lock:
            uid = self._next_uid
            self._next_uid += 1
            return uid

    def add_lock(self, label: str, target: Target, vtype: ValueType,
                 value, enabled: bool = True, note: str = "",
                 uid: int | None = None, slot: str = "") -> LockEntry:
        with self._lock:
            e = LockEntry(uid or self.new_uid(), label, target, vtype,
                          float(value), enabled, note, slot)
            self.locks[e.uid] = e
            return e

    def find_lock_by_slot(self, slot: str) -> LockEntry | None:
        with self._lock:
            for e in self.locks.values():
                if e.slot == slot:
                    return e
        return None

    def remove_lock(self, uid: int) -> None:
        with self._lock:
            self.locks.pop(uid, None)

    def set_lock_value(self, uid: int, value) -> None:
        with self._lock:
            if uid in self.locks:
                self.locks[uid].value = float(value)

    def set_lock_enabled(self, uid: int, enabled: bool) -> None:
        with self._lock:
            if uid in self.locks:
                self.locks[uid].enabled = bool(enabled)

    def get_lock(self, uid: int) -> LockEntry | None:
        with self._lock:
            return self.locks.get(uid)

    # -------------------------------------------------- 监视项

    def add_monitor(self, label: str, target: Target, vtype: ValueType,
                    uid: int | None = None) -> MonitorEntry:
        with self._lock:
            e = MonitorEntry(uid or self.new_uid(), label, target, vtype)
            self.monitors[e.uid] = e
            return e

    def remove_monitor(self, uid: int) -> None:
        with self._lock:
            self.monitors.pop(uid, None)

    def snapshot(self) -> tuple[list[LockEntry], list[MonitorEntry]]:
        with self._lock:
            return (sorted(self.locks.values(), key=lambda e: e.uid),
                    sorted(self.monitors.values(), key=lambda e: e.uid))

    # -------------------------------------------------- 主循环

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            try:
                self._tick()
            except Exception:
                pass
            self.ticks += 1
            self.last_tick = time.time()
            sleep = self.interval - (time.time() - started)
            self._stop.wait(max(0.005, sleep))

    def _tick(self) -> None:
        ctx = self._ctx
        if ctx is None or not ctx.proc or not ctx.proc.opened:
            return

        with self._lock:
            locks = list(self.locks.values())
            monitors = list(self.monitors.values())

        for e in locks:
            if not e.enabled:
                continue
            addr = e.target.resolve(ctx)
            if not addr:
                e.last_error = "地址未解析（模块未加载或指针失效）"
                continue
            try:
                ok = ctx.proc.write(addr, e.vtype.pack(e.value))
            except Exception as exc:
                e.last_error = str(exc)
                continue
            if ok:
                e.writes += 1
                e.last_error = ""

        for e in monitors:
            addr = e.target.resolve(ctx)
            if not addr:
                e.last_error = "地址未解析"
                continue
            raw = ctx.proc.read(addr, e.vtype.size)
            if raw is None:
                continue
            try:
                val = e.vtype.unpack(raw)
            except Exception:
                continue
            if e.value is not None and val != e.value:
                e.prev = e.value
            if e.value != val:
                e.value = val
