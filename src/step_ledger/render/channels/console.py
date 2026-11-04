"""控制台渠道：落 report.md + milestones.md，并把结论直接打到终端。"""

from __future__ import annotations

import json
from pathlib import Path

from ..base import BaseChannel
from ..monthly import day_spend, month_spend, pace, spend_plan
from ..trend import write as write_trend
from ...shared.profile import format_money, goal_plan
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

        artifacts = [report_path, milestones_path]
        artifacts += write_trend(ctx.archive_dir.parent, ctx.archive_dir)

        if ctx.echo:
            print(report)
        return RenderResult(channel=self.name, output=report, artifacts=artifacts)

    def _report(self, judgment: Judgment, ctx: RenderContext) -> str:
        target, savings, distance, percent, from_materials = _goal_view(ctx)
        lines = [
            f"# {ctx.date} · 跬步账",
            f"最近怎么样：{judgment.summary}",
            f"下一步怎么走：{judgment.advice}",
            "",
            "## 离目标还有多远",
            f"- 目标：{format_money(target)}",
            f"- 当前存款：{_savings_text(savings, from_materials)}",
            f"- 还差：{'未知' if distance is None else format_money(distance)}",
            f"- 进度：{_progress_line(percent)}",
        ]
        spending = month_spend(ctx.archive_dir.parent, ctx.date)
        budget = spend_plan(ctx.profile, ctx.date, spending.net_out) if spending is not None else None
        if spending is not None:
            lines.append(self._month_line(spending, budget))
        if budget is not None:
            today_out = day_spend(ctx.archive_dir.parent, ctx.date)
            lines.append(self._pace_line(pace(budget, ctx.date, today_out)))
        deadline, months, per_month = _plan_view(ctx)
        if deadline is not None and months is not None and per_month is not None:
            lines.append(
                f"- 目标日期：{deadline}（还剩 {months} 个月，"
                f"每月要存 {format_money(per_month)}，不计收益）"
            )
        if ctx.profile_created:
            lines += ["", "> 第一次见：把你的目标和存款写进 `materials/profile.md`，我下次就记住了。"]
        if judgment.degraded:
            lines += ["", "> 降级模式：AI 暂时不可用，这条是用本地模板说的，仅供参考。"]
        lines += ["", "_仅供参考，不构成投资建议。_"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _pace_line(p) -> str:  # noqa: ANN001 - 只在这个文件内部用
        parts = [f"今日额度 {format_money(p.quota)}（{p.days} 天均摊）"]
        if p.today_spent is None:
            parts.append("今天还没记账")
        else:
            parts.append(f"今天花了 {format_money(p.today_spent)}")
        if p.month_over:
            parts.append(f"超 {format_money(-p.left)}，本月额度已用完")
        elif p.over:
            tail = f"超 {format_money(-p.left)}"
            if p.tomorrow is not None:
                tail += f"，明天降到 {format_money(p.tomorrow)} 匀回来"
            parts.append(tail)
        else:
            tail = f"结余 {format_money(p.left)}"
            if p.tomorrow is not None:
                tail += f"，明天照 {format_money(p.tomorrow)}"
            parts.append(tail)
        return "- " + " ｜ ".join(parts)

    @staticmethod
    def _month_line(spending, plan) -> str:  # noqa: ANN001 - 只在这个文件内部用
        basis = f"{spending.since[5:]} 起算" if spending.partial else f"{spending.since[5:]}→{spending.until[5:]}"
        if plan is None:
            return f"- 本月已花：{format_money(spending.net_out)}（{basis}）"
        head = (
            f"- 本月可花：{format_money(plan.spendable)}"
            f"（月收入 {format_money(plan.income)} − 需存 {format_money(plan.saving)}）；"
            f"已花 {format_money(spending.net_out)}，"
        )
        return head + (f"已超 {format_money(-plan.left)}" if plan.short else f"还能花 {format_money(plan.left)}")

    def _milestones(self, ctx: RenderContext) -> str:
        entries = _history(ctx.archive_dir.parent)
        target, savings, distance, percent, from_materials = _goal_view(ctx)
        lines = [
            "# 目标里程碑",
            "",
            f"- 目标：{format_money(target)}",
            f"- 当前存款：{_savings_text(savings, from_materials)}",
            f"- 还差：{'未知' if distance is None else format_money(distance)}",
            f"- 进度：{_progress_line(percent)}",
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


def _goal_view(ctx: RenderContext) -> tuple[int, int | None, int | None, float | None, bool]:
    """目标四项：优先读判断层算好的事实，旧路径才退回档案。"""
    if ctx.facts is not None:
        goal = ctx.facts.goal
        return (
            goal.target,
            goal.savings,
            goal.distance,
            goal.percent,
            goal.savings_source == "balance",
        )
    return (
        ctx.profile.target,
        ctx.profile.savings,
        ctx.profile.distance,
        ctx.profile.percent,
        ctx.profile.savings_from_materials,
    )


def _plan_view(ctx: RenderContext) -> tuple[str | None, int | None, int | None]:
    """目标日期的倒推：事实里有就用事实，旧路径退回档案。"""
    if ctx.facts is not None:
        goal = ctx.facts.goal
        return goal.deadline, goal.months, goal.per_month
    plan = goal_plan(ctx.profile, ctx.date)
    if plan is None:
        return None, None, None
    return plan.deadline, plan.months, plan.per_month


def _savings_text(savings: int | None, from_materials: bool) -> str:
    text = format_money(savings)
    if savings is not None and from_materials:
        return f"{text}（AI 从素材识别）"
    return text


def _progress_line(percent: float | None) -> str:
    if percent is None:
        return "未填写存款，暂时画不出进度条"
    filled = int(round(percent * BAR_CELLS))
    bar = "█" * filled + "░" * (BAR_CELLS - filled)
    return f"{bar} {percent * 100:.1f}%"


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
        facts = data.get("facts") if isinstance(data.get("facts"), dict) else {}
        goal = facts.get("goal") if isinstance(facts.get("goal"), dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        progress = meta.get("progress") if isinstance(meta.get("progress"), dict) else {}
        if not goal and not progress:
            continue
        entries.append(
            {
                "date": facts.get("date") or meta.get("date") or day_dir.name,
                "savings": goal.get("savings", progress.get("savings")),
                "percent": goal.get("percent", progress.get("percent")),
            }
        )
    return entries


__all__ = ["ConsoleChannel"]
