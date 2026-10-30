"""跨层共享的数据类型。层间只通过这里定义的结构对话。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .profile import Profile


@dataclass
class Judgment:
    """判断层的产物：一句有温度的花销总结 + 一条可执行的理财建议。"""

    summary: str
    advice: str
    prompt: str = ""
    degraded: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return bool(self.summary.strip()) and bool(self.advice.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "advice": self.advice,
            "prompt": self.prompt,
            "degraded": self.degraded,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Judgment":
        return cls(
            summary=str(data.get("summary", "")),
            advice=str(data.get("advice", "")),
            prompt=str(data.get("prompt", "")),
            degraded=bool(data.get("degraded", False)),
            meta=dict(data.get("meta") or {}),
        )


@dataclass
class CollectResult:
    """采集层的产物：当天素材目录，以及这次新增/跳过的文件。"""

    materials_dir: Path
    files: list[Path] = field(default_factory=list)
    added: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class RenderContext:
    """渲染层需要的上下文：日期、归档目录、档案快照。"""

    date: str
    archive_dir: Path
    profile: Profile
    material_count: int = 0
    profile_created: bool = False
    echo: bool = True


@dataclass
class RenderResult:
    """渲染层的产物：渠道名、给人看的输出、落盘文件。"""

    channel: str
    output: str = ""
    artifacts: list[Path] = field(default_factory=list)


@dataclass
class PipelineResult:
    """一次管线运行的全部结果，供 CLI / agent 转述。"""

    date: str
    materials_dir: Path
    archive_dir: Path
    judgment: Judgment | None = None
    renders: list[RenderResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    stage: str = "all"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "stage": self.stage,
            "materials_dir": str(self.materials_dir),
            "archive_dir": str(self.archive_dir),
            "skipped": self.skipped,
            "judgment": None if self.judgment is None else self.judgment.to_dict(),
            "renders": [
                {
                    "channel": r.channel,
                    "output": r.output,
                    "artifacts": [str(p) for p in r.artifacts],
                }
                for r in self.renders
            ],
        }
