"""素材夹适配器：把被快捷指令自动写入的文件夹（例如 iCloud 里的账单记录）收进当天素材。

只挑文件、不解读内容。归属日期优先看文件名里的 `20261028` / `2026-10-28`，
文件名没有日期时才看修改时间。

素材夹里的文件常常一天内被反复追加，所以按**原文件名覆盖**：同一份源文件当天
只有最新快照，不会因为内容变了就在素材夹里多出一份副本。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..base import BaseAdapter
from ...shared.types import CollectResult
from .manual import READABLE_SUFFIXES, material_files

DATE_IN_NAME = re.compile(r"(20\d{2})-?(\d{2})-?(\d{2})")
LEGACY_VERSION = re.compile(r"^(?P<stem>.+)-[0-9a-f]{8}(?P<suffix>\.[^.]+)$")


class FolderAdapter(BaseAdapter):
    """从一个素材夹里挑出属于某一天的文件。"""

    name = "folder"

    def __init__(self, date: str):
        self.date = date

    def collect(self, materials_dir: Path, payload: str | Path | None = None) -> CollectResult:
        materials_dir.mkdir(parents=True, exist_ok=True)
        result = CollectResult(materials_dir=materials_dir)

        if payload is None or not str(payload).strip():
            return result

        source = Path(str(payload)).expanduser()
        if not source.is_dir():
            result.skipped.append(f"{source.name or source}: 素材夹不存在")
            return result

        matched = 0
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            if self._file_date(path) != self.date:
                continue
            matched += 1
            if path.suffix.lower() not in READABLE_SUFFIXES:
                result.skipped.append(f"{path.name}: 不支持的格式")
                continue
            try:
                target = self._store_latest(path, materials_dir)
            except OSError as exc:
                result.skipped.append(f"{path.name}: 读取失败（{exc}）")
                continue
            if target is not None:
                result.added.append(target)

        if matched == 0:
            result.skipped.append(f"{source.name}: 没有 {self.date} 的素材")

        result.files = material_files(materials_dir)
        return result

    def _file_date(self, path: Path) -> str:
        match = DATE_IN_NAME.search(path.stem)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        try:
            return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
        except OSError:
            return ""

    def _store_latest(self, source: Path, materials_dir: Path) -> Path | None:
        """按原文件名写当天最新快照；内容没变则跳过（幂等）。"""
        data = source.read_bytes()
        target = materials_dir / f"{source.stem}{source.suffix.lower()}"
        if target.is_file() and target.read_bytes() == data:
            return None
        self._drop_hashed_versions(source, materials_dir)
        target.write_bytes(data)
        return target

    @staticmethod
    def _drop_hashed_versions(source: Path, materials_dir: Path) -> None:
        """清掉旧写法（`原名-哈希`）留下的同源副本，避免旧版本和新快照同时进 prompt。"""
        stem, suffix = source.stem, source.suffix.lower()
        for path in materials_dir.iterdir():
            match = LEGACY_VERSION.match(path.name)
            if path.is_file() and match and match["stem"] == stem and match["suffix"] == suffix:
                path.unlink(missing_ok=True)


def collect(materials_dir: Path, source_dir: str | Path, date: str) -> CollectResult:
    return FolderAdapter(date).collect(materials_dir, source_dir)


__all__ = ["FolderAdapter", "collect"]
