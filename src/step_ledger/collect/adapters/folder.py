"""素材夹适配器：把被快捷指令自动写入的文件夹（例如 iCloud 里的账单记录）收进当天素材。

只挑文件、不解读内容。归属日期优先看文件名里的 `20261028` / `2026-10-28`，
文件名没有日期时才看修改时间。落盘沿用「原名-内容哈希」约定，同日重复收不会产生副本。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..base import BaseAdapter
from ...shared.types import CollectResult
from .manual import READABLE_SUFFIXES, material_files, store_file

DATE_IN_NAME = re.compile(r"(20\d{2})-?(\d{2})-?(\d{2})")


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
                target = store_file(path, materials_dir)
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


def collect(materials_dir: Path, source_dir: str | Path, date: str) -> CollectResult:
    return FolderAdapter(date).collect(materials_dir, source_dir)


__all__ = ["FolderAdapter", "collect"]
