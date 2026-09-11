# -*- coding: utf-8 -*-
"""路径与配置：定位游戏目录、存档目录、工具自身目录。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "AliceInCradle"
APP_EXE = "AliceInCradle.exe"
COMPANY = "NanameHacha"
PRODUCT = "AliceInCradle"
DEBUG_TXT_REL = Path("AliceInCradle_Data") / "StreamingAssets" / "_debug.txt"

# ---------------------------------------------------------------- 工具自身目录

def app_root() -> Path:
    """AIC修改器/ 目录。"""
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """配置目录。

    环境变量 `AIC_CONFIG_DIR` 可改写位置 —— 自测脚本用它把配置隔离到临时目录，
    免得把用户真实的 `config/trainer.json` 写脏（热键开关之类的改动会被留在里面）。
    """
    override = os.environ.get("AIC_CONFIG_DIR")
    if override:
        return Path(override)
    return app_root() / "config"


def backup_dir() -> Path:
    return app_root() / "backup"


def logs_dir() -> Path:
    return app_root() / "logs"


def _ensure(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return _ensure(config_dir()) / "trainer.json"


# ---------------------------------------------------------------- 用户配置

DEFAULT_CONFIG = {
    "game_dir": "",
    "hotkeys_enabled": True,
    "hotkeys": {
        "invincible": "F1",
        "infinite_mp": "F2",
        "one_hit_kill": "F3",
        "add_money": "F4",
        "speed_cycle": "F5",
        # 「一键」页找数值时用：在游戏里直接告诉工具「我刚把它变小 / 变大了」
        "smaller": "F8",
        "bigger": "F9",
    },
    "presets": [],
    "autobackup_saves": True,
    # 游戏一启动就自动连上，省掉手动点「附加」
    "auto_attach": True,
    "theme": "dark",
    # 界面缩放："auto" 跟随系统 DPI 缩放，也可写 "150%" 或 1.5
    "ui_scale": "auto",
    # 上次关闭时的窗口位置，形如 "1800x1230+120+60"；空串表示按缩放自动给一个尺寸
    "window_geometry": "",
    "scan": {
        "include_readonly": False,
        "include_mapped": False,
    },
}


def load_config() -> dict:
    p = config_path()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _deep_merge(cfg, data)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    p = config_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _deep_merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------- 游戏目录定位

# 已知/常见安装位置的启发式候选（含大小写与浅层通配）
_SEARCH_ROOTS = [
    r"D:\Games",
    r"D:\SteamLibrary\steamapps\common",
    r"C:\Games",
    r"E:\Games",
]


def is_game_dir(p: Path) -> bool:
    try:
        return (p / APP_EXE).is_file() and (p / "AliceInCradle_Data").is_dir()
    except OSError:
        return False


def _self_relative() -> Path | None:
    """修改器直接放在游戏目录里（或紧邻其下）时，按相对位置认出来 —— 最可靠。

    依次看 app_root() 上 1~3 层：容忍 AIC修改器/ 直接躺在游戏根目录，
    或躺在游戏根目录下的某个子文件夹里。

    找不到就再从**父目录往下浅搜**：v0.30 的官方压缩包解开后是多层嵌套
    （`...Win ver030f/AliceInCradle Win ver030/AliceInCradle_ver030/`），
    玩家很容易把 `AIC修改器/` 放在最外层，这时向上是找不到 exe 的。
    """
    base = app_root()
    up = base
    for _ in range(3):
        up = up.parent
        if up == up.parent:          # 已到盘符根，别再往上
            break
        try:
            if is_game_dir(up):
                return up
        except OSError:
            continue

    # 向下兜底：从父目录起浅搜，能穿透 v0.30 那种两层套娃的解压目录
    parent = base.parent
    if parent != base:
        try:
            for sub in _walk_limited(parent, max_depth=3):
                if sub == base:
                    continue
                if is_game_dir(sub):
                    return sub
        except OSError:
            pass
    return None


def find_game_dir(explicit: str = "") -> Path | None:
    """按 自身相对位置 -> 显式配置 -> 常见根目录搜索 的顺序定位。"""
    self_dir = _self_relative()
    if self_dir is not None:
        return self_dir

    if explicit:
        p = Path(explicit)
        if is_game_dir(p):
            return p
        # 允许用户直接填外层文件夹
        for sub in _walk_limited(p, max_depth=3):
            if is_game_dir(sub):
                return sub

    for root in _SEARCH_ROOTS:
        rp = Path(root)
        if not rp.is_dir():
            continue
        for sub in _walk_limited(rp, max_depth=4):
            if is_game_dir(sub):
                return sub
    return None


def _walk_limited(root: Path, max_depth: int):
    """广度优先、跳过明显无关目录的浅层遍历。"""
    if not root.is_dir():
        return
    skip = {
        "$RECYCLE.BIN", "System Volume Information", "node_modules",
        "AppData", "Windows", "Program Files", "Program Files (x86)",
        "Python", ".git", "$WinREAgent",
    }
    queue: list[tuple[Path, int]] = [(root, 0)]
    while queue:
        cur, depth = queue.pop(0)
        yield cur
        if depth >= max_depth:
            continue
        try:
            for child in os.scandir(cur):
                try:
                    if not child.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if child.name in skip or child.name.startswith("."):
                    continue
                queue.append((Path(child.path), depth + 1))
        except (PermissionError, OSError):
            continue


def game_exe(game_dir: Path) -> Path:
    return game_dir / APP_EXE


def debug_txt(game_dir: Path) -> Path:
    return game_dir / DEBUG_TXT_REL


# ---------------------------------------------------------------- 存档目录

def save_dir() -> Path:
    """%USERPROFILE%\\AppData\\LocalLow\\NanameHacha\\AliceInCradle"""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        local = str(Path.home() / "AppData" / "Local")
    return Path(local) / ".." / "LocalLow" / COMPANY / PRODUCT


def save_files() -> list[Path]:
    d = save_dir()
    if not d.is_dir():
        return []
    out: list[Path] = []
    for pat in ("savedata_*.aicsave", "whole.data", "config.cfg"):
        out.extend(sorted(d.glob(pat)))
    return out


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def python_exe() -> str:
    """当前解释器（供 .bat 复用）。"""
    return sys.executable
