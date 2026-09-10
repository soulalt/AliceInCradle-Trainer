# -*- coding: utf-8 -*-
"""游戏内置调试开关：读写 AliceInCradle_Data/StreamingAssets/_debug.txt

设计要点（面向「绝不弄坏原文件」）：
  1. 只改目标键所在行的「值」这一小段，其余内容（缩进、注释、行序、换行符）逐字节保留。
  2. 首次修改前保存 _debug.txt.orig.bak（只写一次，永不覆盖）。
  3. 每次修改前把当前内容存成 _debug.txt.bak，可一键回滚到上一次状态。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

# 键名 -> 中文说明（说明来自游戏自带注释）
FLAG_INFO: dict[str, str] = {
    "DEBUG": "总调试开关（游戏自带的开关总闸，保持 1）",
    "mighty": "攻击力超强：普通攻击即可秒掉小怪",
    "nodamage": "免伤：诺艾儿受到的伤害降为 0",
    "weak": "纸片人模式（一碰就倒，反向开关，慎用）",
    "allskill": "解锁全部隐藏技能",
    "albumunlock": "解锁相册内容",
    "supercyclone": "启用旋风（历史 glitch，0.21 起默认为开）",
    "announce": "启动时提示上一次的错误日志（F7 调试菜单前置条件之一）",
    "timestamp": "日志加时间戳（F7 调试菜单前置条件之一）",
    "nosnd": "不加载音频资源（缩短读取时间，会静音）",
    "reloadmtr": "启用 F9 热重载本地化文本",
    "nocfg": "忽略读取任何设置",
    "noevent": "禁用事件",
    "novoice": "禁用语音",
    "sensitive": "敏感内容相关开关",
    "speffect": "特效相关开关",
    "supersensitive": "更高敏感度开关",
    "benchmark": "性能基准模式",
    "stabilize_draw": "稳定绘制（降低卡顿）",
    "_player": "玩家内部开关（建议保持 0）",
}

# 面板上按这个顺序展示
PANEL_ORDER = ["DEBUG", "mighty", "nodamage", "allskill", "albumunlock",
               "announce", "timestamp", "weak", "noevent", "novoice"]

F7_MENU_KEYS = ("announce", "timestamp")


@dataclass
class FlagEntry:
    key: str
    value: int
    desc: str
    known: bool = True


class DebugFlags:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lines: list[str] = []
        self._index: dict[str, int] = {}
        self._raw: dict[str, str] = {}
        self.dirty = False
        self.last_error = ""

    # -------------------------------------------------- 备份路径

    @property
    def orig_backup(self) -> Path:
        return self.path.with_name(self.path.name + ".orig.bak")

    @property
    def rollback_backup(self) -> Path:
        return self.path.with_name(self.path.name + ".bak")

    # -------------------------------------------------- 读

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict[str, int]:
        self._lines = []
        self._index = {}
        self._raw = {}
        if not self.exists():
            self.last_error = f"找不到文件：{self.path}"
            return {}
        # newline='' 保持原始换行符（CRLF/LF）不被转换
        with open(self.path, "r", encoding="utf-8-sig", newline="") as fh:
            self._lines = fh.readlines()
        for i, line in enumerate(self._lines):
            m = _LINE_RE.match(line)
            if not m:
                continue
            key, value = _norm(m.group("key")), m.group("value")
            if not _is_int(value):
                continue
            self._index[key] = i
            self._raw[key] = value
        return self.values()

    def values(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for key, i in self._index.items():
            m = _LINE_RE.match(self._lines[i])
            if m and _is_int(m.group("value")):
                out[key] = int(m.group("value"))
        return out

    def entries(self) -> list[FlagEntry]:
        vals = self.values()
        out: list[FlagEntry] = []
        for key in PANEL_ORDER:
            if key in vals:
                out.append(FlagEntry(key, vals[key], FLAG_INFO.get(key, ""), True))
        for key, v in vals.items():
            if key not in PANEL_ORDER:
                out.append(FlagEntry(key, v, FLAG_INFO.get(key, ""), key in FLAG_INFO))
        return out

    def get(self, key: str) -> int | None:
        return self.values().get(key)

    # -------------------------------------------------- 写

    def set(self, key: str, value: int, backup: bool = True) -> bool:
        return self.set_many({key: value}, backup=backup)

    def set_many(self, mapping: dict[str, int], backup: bool = True) -> bool:
        self.last_error = ""
        if not self._index:
            self.load()
        if not self._index:
            return False

        changed = False
        new_lines = list(self._lines)
        for key, value in mapping.items():
            i = self._index.get(key)
            if i is None:
                self.last_error = f"文件中没有开关：{key}"
                continue
            line = new_lines[i]
            m = _LINE_RE.match(line)
            if not m:
                continue
            if int(m.group("value")) == int(value):
                continue
            new_lines[i] = (
                m.group("prefix") + str(int(value)) + m.group("suffix")
            )
            changed = True

        if not changed:
            return True

        if backup:
            self._make_backups()
        try:
            with open(self.path, "w", encoding="utf-8", newline="") as fh:
                fh.writelines(new_lines)
        except OSError as exc:
            self.last_error = f"写入失败：{exc}"
            return False
        self._lines = new_lines
        self.dirty = True
        return True

    def unlock_f7_menu(self, backup: bool = True) -> bool:
        """按游戏注释所述，announce + timestamp 同时为 1 才会出现 F7 调试菜单。"""
        return self.set_many({k: 1 for k in F7_MENU_KEYS}, backup=backup)

    def _make_backups(self) -> None:
        try:
            if not self.orig_backup.exists() and self.path.exists():
                shutil.copy2(self.path, self.orig_backup)
            if self.path.exists():
                shutil.copy2(self.path, self.rollback_backup)
        except OSError:
            pass

    # -------------------------------------------------- 还原

    def restore(self, source: str = "orig", backup: bool = True) -> bool:
        """source: 'orig' 还原到最初版本；'rollback' 回滚到上一次修改前。"""
        src = self.orig_backup if source == "orig" else self.rollback_backup
        self.last_error = ""
        if not src.exists():
            self.last_error = f"没有可用的备份：{src.name}"
            return False
        if backup and self.path.exists():
            try:
                shutil.copy2(self.path, self.path.with_name(self.path.name + ".before_restore"))
            except OSError:
                pass
        try:
            shutil.copy2(src, self.path)
        except OSError as exc:
            self.last_error = f"还原失败：{exc}"
            return False
        self.load()
        return True

    def diff_summary(self) -> list[str]:
        """返回与原始备份的差异（用于自检/展示）。"""
        out: list[str] = []
        if not self.orig_backup.exists() or not self.path.exists():
            return out
        a = self.orig_backup.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        b = self.path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        for i in range(max(len(a), len(b))):
            x = a[i] if i < len(a) else "<无>"
            y = b[i] if i < len(b) else "<无>"
            if x != y:
                out.append(f"第 {i+1} 行:\n  - {x}\n  + {y}")
        return out


# 结构：前缀(key + 空白) + 值 + 其后所有内容（含空格、注释与行尾换行符）
# suffix 用 DOTALL 抓取，确保原样保留 CRLF/LF，重写后文件长度与行数都不变。
_LINE_RE = re.compile(
    r"^(?P<prefix>(?P<key><[A-Za-z_]\w*>|[A-Za-z_]\w*)[ \t]+)"
    r"(?P<value>\S+)(?P<suffix>.*)$",
    re.DOTALL,
)


def _is_int(text: str) -> bool:
    try:
        int(text)
        return True
    except (TypeError, ValueError):
        return False


def _norm(key: str) -> str:
    """<DEBUG> -> DEBUG，其余原样。"""
    return key.strip().strip("<>")
