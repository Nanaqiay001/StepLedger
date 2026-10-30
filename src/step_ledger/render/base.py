"""渲染层：把 Judgment 变成人愿意看一眼的东西，并归档。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..shared.types import Judgment, RenderContext, RenderResult


class BaseChannel(ABC):
    """渲染渠道的扩展点。终端 / 图片 / 网页都实现同一个接口。"""

    name: str = "base"

    @abstractmethod
    def render(self, judgment: Judgment, ctx: RenderContext) -> RenderResult:
        raise NotImplementedError
