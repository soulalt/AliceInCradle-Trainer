# -*- coding: utf-8 -*-
"""预设：把「已定位好的地址」保存下来，下次一键套用（支持直接地址与指针链）。"""

from __future__ import annotations

from .freezer import Freezer, LockEntry, MonitorEntry, Target
from .scanner import VALUE_TYPES, ValueType

# 与热键一一对应的功能槽位（预设可按这些名字命名以被热键驱动）
ACTION_LABELS = {
    "invincible": "无敌 / 免伤",
    "infinite_mp": "无限魔力",
    "one_hit_kill": "一击必杀",
    "add_money": "金币 +99999",
    "speed_cycle": "速度倍率循环",
    # 「一键」页找数值专用（不是开关，是"我刚让它变小/变大了"）
    "smaller": "一键页：它变小了",
    "bigger": "一键页：它变大了",
}


def make_preset(name: str, target: Target, vtype: ValueType, value,
                lock: bool = True, note: str = "", slot: str = "") -> dict:
    return {
        "name": name,
        "slot": slot,
        "target": target.to_dict(),
        "type": vtype.key,
        "value": float(value),
        "lock": bool(lock),
        "note": note,
    }


def vtype_of(preset: dict) -> ValueType:
    return VALUE_TYPES.get(preset.get("type", "4bytes"), VALUE_TYPES["4bytes"])


def apply_preset(preset: dict, freezer: Freezer) -> LockEntry:
    """把预设加入锁定表（同 slot / 同名已存在则更新，而不是重复添加）。"""
    target = Target.from_dict(preset.get("target", {}))
    vtype = vtype_of(preset)
    name = preset.get("name", "未命名")
    slot = preset.get("slot", "")

    existing = freezer.find_lock_by_slot(slot) if slot else None
    if existing is None:
        for e in freezer.locks.values():
            if e.label == name:
                existing = e
                break
    if existing is not None:
        existing.target = target
        existing.vtype = vtype
        existing.value = float(preset.get("value", 0))
        existing.enabled = bool(preset.get("lock", True))
        existing.note = preset.get("note", "")
        existing.slot = slot
        return existing

    return freezer.add_lock(name, target, vtype, float(preset.get("value", 0)),
                            enabled=bool(preset.get("lock", True)),
                            note=preset.get("note", ""), slot=slot)


def monitor_from_preset(preset: dict, freezer: Freezer) -> MonitorEntry:
    return freezer.add_monitor(
        preset.get("name", "监视"),
        Target.from_dict(preset.get("target", {})),
        vtype_of(preset),
    )


def find_by_slot(presets: list[dict], slot: str) -> dict | None:
    for p in presets:
        if p.get("slot") == slot:
            return p
    return None


def replace_or_add(presets: list[dict], preset: dict) -> list[dict]:
    name, slot = preset.get("name"), preset.get("slot")
    out = []
    replaced = False
    for p in presets:
        if (slot and p.get("slot") == slot) or (not slot and p.get("name") == name):
            if not replaced:
                out.append(preset)
                replaced = True
        else:
            out.append(p)
    if not replaced:
        out.append(preset)
    return out


def remove(presets: list[dict], name: str) -> list[dict]:
    return [p for p in presets if p.get("name") != name]
