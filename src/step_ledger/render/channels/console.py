"""控制台渠道：落 report.md + milestones.md，并把结论直接打到终端。"""

from __future__ import annotations

import json
from pathlib import Path

from ..base import BaseChannel
from ...shared.profile import Profile, format_money
from ...shared.types import Judgment, RenderContext, RenderResult

BAR_CELLS = 10
HISTORY_LIMIT = 14


class ConsoleChannel(BaseChannel):
    name = "console"

    def render(self, judgment: Judgment, ctx: RenderContext) -> RenderResult:
        ctx.archive_dir.mkdir(parents=True, exist_ok=True)
        report = self._report(judgment, ctx)
        report_path = ctx.archive_dir / "report.md"
        report_path.write_text(report, encoding="utf-8")

        milestones_path = ctx.archive_dir / "milestones.md"
        milestones_path.write_text(self._milestones(ctx), encoding="utf-8")

        if ctx.echo:
            print(report)
        return RenderResult(channel=self.name, output=report, artifacts=[report_path, milestones_path])

    def _report(self, judgment: Judgment, ctx: RenderContext) -> str:
        lines = [
            f"# {ctx.date} · 跬步账",
            f"最近怎么样：{judgment.summary}",
            f"下一步怎么走：{judgment.advice}",
            "",
            "## 离目标还有多远",
            f"- 目标：{format_money(ctx.profile.target)}",
            f"- 当前存款：{_savings_text(ctx.profile)}",
            f"- 还差：{'未知' if ctx.profile.distance is None else format_money(ctx.profile.distance)}",
            f"- 进度：{_progress_line(ctx.profile)}",
        ]
        if ctx.profile_created:
            lines += ["", "> 第一次见：把你的目标和存款写进 `materials/profile.md`，我下次就记住了。"]
        if judgment.degraded:
            lines += ["", "> 降级模式：AI 暂时不可用，这条是用本地模板说的，仅供参考。"]
        lines += ["", "_仅供参考，不构成投资建议。_"]
        return "\n".join(lines) + "\n"

    def _milestones(self, ctx: RenderContext) -> str:
        entries = _history(ctx.archive_dir.parent)
        lines = [
            "# 目标里程碑",
            "",
            f"- 目标：{format_money(ctx.profile.target)}",
            f"- 当前存款：{_savings_text(ctx.profile)}",
            f"- 还差：{'未知' if ctx.profile.distance is None else format_money(ctx.profile.distance)}",
            f"- 进度：{_progress_line(ctx.profile)}",
            "",
            "## 最近进度",
            "",
        ]
        if entries:
            lines += ["| 日期 | 当前存款 | 进度 |", "|------|----------|------|"]
            for entry in entries[:HISTORY_LIMIT]:
                savings = entry.get("savings")
                percent = entry.get("percent")
                lines.append(
                    "| {date} | {savings} | {percent} |".format(
                        date=entry.get("date", "?"),
                        savings=format_money(savings) if isinstance(savings, int) else "未填写",
                        percent="—" if percent is None else f"{percent * 100:.1f}%",
                    )
                )
        else:
            lines.append("还在第一天，走两步就有曲线了。")
        return "\n".join(lines) + "\n"


def _savings_text(profile: Profile) -> str:
    text = format_money(profile.savings)
    if profile.savings is not None and profile.savings_from_materials:
        return f"{text}（AI 从素材识别）"
    return text


def _progress_line(profile: Profile) -> str:
    if profile.percent is None:
        return "未填写存款，暂时画不出进度条"
    filled = int(round(profile.percent * BAR_CELLS))
    bar = "█" * filled + "░" * (BAR_CELLS - filled)
    return f"{bar} {profile.percent * 100:.1f}%"


def _history(archive_dir: Path) -> list[dict]:
    """从已归档的 judgment.json 里收集进度快照，最近的排前面。"""
    entries: list[dict] = []
    if not archive_dir.is_dir():
        return entries
    for day_dir in sorted(archive_dir.iterdir(), reverse=True):
        if not day_dir.is_dir():
            continue
        judgment_file = day_dir / "judgment.json"
        if not judgment_file.is_file():
            continue
        try:
            data = json.loads(judgment_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        progress = (data.get("meta") or {}).get("progress")
        if not isinstance(progress, dict):
            continue
        entries.append(
            {
                "date": data.get("meta", {}).get("date", day_dir.name),
                "savings": progress.get("savings"),
                "percent": progress.get("percent"),
            }
        )
    return entries


__all__ = ["ConsoleChannel"]
