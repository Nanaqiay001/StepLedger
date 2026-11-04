"""判断层：把素材读成一句有温度的总结 + 一条建议。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..shared.profile import Profile
from ..shared.types import Facts, Judgment, Observation, TrendSummary


class BaseProvider(ABC):
    """AI Provider 的扩展点。新增模型只要实现 judge()。"""

    name: str = "base"

    @abstractmethod
    def observe(self, materials_text: str, date: str = "") -> Observation:
        """只读余额，不评价。核验由 judge/observe.py 的 verify() 统一做。"""
        raise NotImplementedError

    @abstractmethod
    def speak(
        self,
        materials_dir: Path,
        profile: Profile,
        date: str = "",
        facts: Facts | None = None,
        trend: TrendSummary | None = None,
    ) -> Judgment:
        """基于算好的事实写字。方法叫 speak 而不是 judge，是为了和层名区分。"""
        raise NotImplementedError


class ProviderError(RuntimeError):
    """模型不可用 / 返回不合约定。管线会降级到 stub。"""
