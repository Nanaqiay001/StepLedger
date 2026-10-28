"""手动素材适配器：一段文字或一个文件路径，都落成当天素材。

命名带内容哈希 → 同一天重复投递同一份素材不会产生副本（幂等）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..base import BaseAdapter
from ...shared.types import CollectResult

TEXT_SUFFIX = ".md"
READABLE_SUFFIXES = {".md", ".txt", ".markdown", ".csv", ".log", ".json"}


def digest(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha1(data).hexdigest()[:8]


def material_files(materials_dir: Path) -> list[Path]:
    """当天素材快照：目录下的文件，排除档案本身。"""
    if not materials_dir.is_dir():
        return []
    return sorted(p for p in materials_dir.iterdir() if p.is_file() and p.name != "profile.md")


def store_file(source: Path, materials_dir: Path) -> Path | None:
    """把 source 复制进素材夹，文件名带内容哈希；已存在则返回 None（幂等）。"""
    data = source.read_bytes()
    target = materials_dir / f"{source.stem[:24]}-{digest(data)}{source.suffix.lower()}"
    if target.exists():
        return None
    target.write_bytes(data)
    return target


class ManualAdapter(BaseAdapter):
    name = "manual"

    def collect(self, materials_dir: Path, payload: str | Path | None = None) -> CollectResult:
        materials_dir.mkdir(parents=True, exist_ok=True)
        result = CollectResult(materials_dir=materials_dir)

        if payload is not None:
            path = Path(str(payload)).expanduser()
            if path.exists():
                self._collect_path(path, materials_dir, result)
            else:
                self._collect_text(str(payload), materials_dir, result)

        result.files = material_files(materials_dir)
        return result

    def _collect_text(self, text: str, materials_dir: Path, result: CollectResult) -> None:
        if not text.strip():
            return
        target = materials_dir / f"manual-{digest(text)}{TEXT_SUFFIX}"
        if target.exists():
            return
        target.write_text(text.strip() + "\n", encoding="utf-8")
        result.added.append(target)

    def _collect_path(self, path: Path, materials_dir: Path, result: CollectResult) -> None:
        sources = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        for source in sources:
            if source.suffix.lower() not in READABLE_SUFFIXES:
                result.skipped.append(f"{source.name}: 不支持的格式")
                continue
            try:
                target = store_file(source, materials_dir)
            except OSError as exc:
                result.skipped.append(f"{source.name}: 读取失败（{exc}）")
                continue
            if target is not None:
                result.added.append(target)


def collect(materials_dir: Path, payload: str | Path | None = None) -> CollectResult:
    return ManualAdapter().collect(materials_dir, payload)


__all__ = [
    "ManualAdapter",
    "collect",
    "digest",
    "material_files",
    "store_file",
    "READABLE_SUFFIXES",
]
