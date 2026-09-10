# -*- coding: utf-8 -*-
"""存档备份与还原。

备份对象：%LOCALAPPDATA%\\..\\LocalLow\\NanameHacha\\AliceInCradle 下的
savedata_*.aicsave / whole.data / config.cfg（不含 Unity 分析数据）。
每次备份落在 backup/<时间戳>_<标签>/，内含 manifest.json（含 sha256）。
还原前会先自动做一次 tag=prerestore 的安全备份，保证操作可逆。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .paths import backup_dir, human_size, save_dir, save_files


@dataclass
class BackupInfo:
    path: Path
    tag: str
    created: str
    files: list[dict] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(int(f.get("size", 0)) for f in self.files)

    @property
    def title(self) -> str:
        return f"{self.created}  [{self.tag}]  {len(self.files)} 个文件 / {human_size(self.total_size)}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def create_backup(tag: str = "manual") -> tuple[Path | None, str]:
    files = save_files()
    if not files:
        return None, f"没有找到存档文件（{save_dir()}）"
    target = backup_dir() / f"{_timestamp()}_{tag}"
    n = 1
    while target.exists():
        target = backup_dir() / f"{_timestamp()}_{tag}-{n}"
        n += 1
    target.mkdir(parents=True, exist_ok=True)

    manifest_files: list[dict] = []
    errors: list[str] = []
    for src in files:
        try:
            shutil.copy2(src, target / src.name)
            manifest_files.append({
                "name": src.name,
                "size": src.stat().st_size,
                "sha256": sha256_file(target / src.name),
            })
        except OSError as exc:
            errors.append(f"{src.name}: {exc}")

    manifest = {
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tag": tag,
        "source_dir": str(save_dir()),
        "files": manifest_files,
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    msg = f"已备份 {len(manifest_files)} 个文件到 {target.name}"
    if errors:
        msg += "；失败：" + "；".join(errors)
    return target, msg


def list_backups() -> list[BackupInfo]:
    root = backup_dir()
    if not root.is_dir():
        return []
    out: list[BackupInfo] = []
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        mf = d / "manifest.json"
        meta = {}
        if mf.is_file():
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        files = meta.get("files")
        if not files:
            files = [
                {"name": f.name, "size": f.stat().st_size}
                for f in d.iterdir() if f.is_file() and f.name != "manifest.json"
            ]
        out.append(BackupInfo(
            path=d,
            tag=meta.get("tag", "未知"),
            created=meta.get("created", d.name),
            files=files,
        ))
    return out


def restore_backup(bp: Path, safety_backup: bool = True) -> tuple[bool, str]:
    bp = Path(bp)
    if not bp.is_dir():
        return False, "备份目录不存在"
    dst = save_dir()
    if not dst.is_dir():
        return False, f"存档目录不存在：{dst}"

    if safety_backup:
        create_backup("prerestore")

    restored, errors = [], []
    for f in bp.iterdir():
        if not f.is_file() or f.name == "manifest.json":
            continue
        try:
            shutil.copy2(f, dst / f.name)
            restored.append(f.name)
        except OSError as exc:
            errors.append(f"{f.name}: {exc}")

    if not restored:
        return False, "备份里没有可还原的文件"
    msg = f"已还原 {len(restored)} 个文件：" + "、".join(restored)
    if errors:
        msg += "；失败：" + "；".join(errors)
    return True, msg


def auto_backup(tag: str = "auto", min_interval_minutes: int = 30) -> tuple[Path | None, str]:
    """附加游戏时调用；距上次同名备份不足间隔则跳过，避免刷屏。"""
    for info in list_backups():
        if info.tag == tag:
            try:
                last = datetime.strptime(info.created, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                break
            if (datetime.now() - last).total_seconds() < min_interval_minutes * 60:
                return None, f"距上次自动备份不足 {min_interval_minutes} 分钟，已跳过"
            break
    return create_backup(tag)


def verify_backup(bp: Path) -> list[str]:
    """校验备份内文件的 sha256，返回不一致项。"""
    problems: list[str] = []
    mf = Path(bp) / "manifest.json"
    if not mf.is_file():
        return ["缺少 manifest.json"]
    try:
        meta = json.loads(mf.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"manifest 解析失败：{exc}"]
    for item in meta.get("files", []):
        f = Path(bp) / item["name"]
        if not f.is_file():
            problems.append(f"{item['name']} 缺失")
        elif item.get("sha256") and sha256_file(f) != item["sha256"]:
            problems.append(f"{item['name']} 校验不一致")
    return problems
