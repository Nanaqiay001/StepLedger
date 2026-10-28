"""判断层：把素材读成一句有温度的总结 + 一条建议。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..shared.profile import Profile
from ..shared.types import Judgment


class BaseProvider(ABC):
    """AI Provider 的扩展点。新增模型只要实现 judge()。"""

    name: str = "base"

    @abstractmethod
    def judge(self, materials_dir: Path, profile: Profile, date: str = "") -> Judgment:
        raise NotImplementedError


class ProviderError(RuntimeError):
    """模型不可用 / 返回不合约定。管线会降级到 stub。"""
