"""采集层：只负责把素材落成文件，不解读。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..shared.types import CollectResult


class BaseAdapter(ABC):
    """素材来源的扩展点。新增来源只要实现 collect()。"""

    name: str = "base"

    @abstractmethod
    def collect(self, materials_dir: Path, payload: str | Path | None = None) -> CollectResult:
        """把 payload 落盘到 materials_dir，并返回当天素材快照。"""
        raise NotImplementedError
