"""控制台渠道：落 report.md + milestones.md，并把结论直接打到终端。

这里只排版。已花、可花、额度、超没超、明天该多少全在 `judgment.facts` 里算好了，
渠道不再读 `archive/`、也不再做任何金额运算。
"""

from __future__ import annotations

from ...shared.profile import format_money
from ...shared.types import Facts, GoalFacts, Judgment, MonthFacts, PaceFacts, RenderContext, RenderResult
from ..base import BaseChannel
from ..trend import write as write_trend

BAR_CELLS = 10
HISTORY_LIMIT = 14


class ConsoleChannel(BaseChannel):
    name = "console"

    def render(self, judgment: Judgment, ctx: RenderContext) -> RenderResult:
        ctx.out_dir.mkdir(parents=True, exist_ok=True)
        report = self._report(judgment, ctx)
        report_path = ctx.out_dir / "report.md"
        report_path.write_text(report, encoding="utf-8")

        milestones_path = ctx.out_dir / "milestones.md"
        milestones_path.write_text(self._milestones(judgment), encoding="utf-8")

        artifacts = [report_path, milestones_path]
        artifacts += write_trend(judgment.trend.days, ctx.out_dir)

        if ctx.echo:
            print(report)
            chart = next((path for path in artifacts if path.suffix == ".svg"), None)
            if chart is not None:
                print(f"图表：{chart}（同目录还有 trend.csv）")
        return RenderResult(channel=self.name, output=report, artifacts=artifacts)

    def _report(self, judgment: Judgment, ctx: RenderContext) -> str:
        facts = judgment.facts
        goal = facts.goal if facts is not None else None
        lines = [
            f"# {facts.date if facts is not None else ''} · 跬步账",
            f"最近怎么样：{judgment.summary}",
            f"下一步怎么走：{judgment.advice}",
            "",
            "## 离目标还有多远",
            f"- 目标：{format_money(goal.target if goal is not None else None)}",
            f"- 当前存款：{_savings_text(goal)}",
            f"- 还差：{'未知' if goal is None or goal.distance is None else format_money(goal.distance)}",
            f"- 进度：{_progress_line(goal.percent if goal is not None else None)}",
        ]
        if goal is not None and goal.deadline and goal.months and goal.per_month:
            lines.append(
                f"- 目标日期：{goal.deadline}（还剩 {goal.months} 个月，"
                f"每月要存 {format_money(goal.per_month)}，不计收益）"
            )
        if facts is not None:
            if facts.month is not None:
                lines.append(_month_line(facts))
            if facts.pace is not None:
                lines.append(_pace_line(facts.pace))
            lines += _fact_notes(facts, prose_is_old=bool(judgment.runtime.get("facts_backfilled")))
        if judgment.runtime.get("profile_created"):
            lines += ["", "> 第一次见：把你的目标和存款写进 `materials/profile.md`，我下次就记住了。"]
        if judgment.degraded:
            lines += ["", "> 降级模式：AI 暂时不可用，这条是用本地模板说的，仅供参考。"]
        lines += ["", "_仅供参考，不构成投资建议。_"]
        return "\n".join(lines) + "\n"

    def _milestones(self, judgment: Judgment) -> str:
        facts = judgment.facts
        goal = facts.goal if facts is not None else None
        entries = judgment.trend.progress[-HISTORY_LIMIT:]
        lines = [
            "# 目标里程碑",
            "",
            f"- 目标：{format_money(goal.target if goal is not None else None)}",
            f"- 当前存款：{_savings_text(goal)}",
            f"- 还差：{'未知' if goal is None or goal.distance is None else format_money(goal.distance)}",
            f"- 进度：{_progress_line(goal.percent if goal is not None else None)}",
            "",
            "## 最近进度",
            "",
        ]
        if entries:
            lines += ["| 日期 | 当前存款 | 进度 |", "|------|----------|------|"]
            for point in reversed(entries):
                lines.append(
                    "| {date} | {savings} | {percent} |".format(
                        date=point.day,
                        savings=format_money(point.savings) if isinstance(point.savings, int) else "未填写",
                        percent="—" if point.percent is None else f"{point.percent * 100:.1f}%",
                    )
                )
        else:
            lines.append("还在第一天，走两步就有曲线了。")
        return "\n".join(lines) + "\n"


def _savings_text(goal: GoalFacts | None) -> str:
    if goal is None or goal.savings is None:
        return "未填写"
    text = format_money(goal.savings)
    if goal.savings_source == "balance":
        return f"{text}（按素材余额估算）"
    return text


def _progress_line(percent: float | None) -> str:
    if percent is None:
        return "未填写存款，暂时画不出进度条"
    filled = int(round(percent * BAR_CELLS))
    bar = "█" * filled + "░" * (BAR_CELLS - filled)
    return f"{bar} {percent * 100:.1f}%"


def _month_line(facts: Facts) -> str:
    month = facts.month
    if month is None:
        return "- 本月已花：算不出来"
    if month.spent is None:
        if month.baseline is None:
            return "- 本月已花：月初还没有更早的余额，算不出来"
        return f"- 本月已花：算不出来（只有 {month.baseline_date[5:]} 一条余额）"
    spent = f"已花 {format_money(month.spent)}"
    if month.spent_as_of and month.spent_as_of != facts.date:
        spent += f"（截至 {month.spent_as_of[5:]}）"
    if month.spendable is None:
        return f"- 本月已花：{format_money(month.spent)}（档案里缺少月收入或目标日期，算不出可花）"
    head = f"- 本月可花：{format_money(month.spendable)}"
    if month.income is not None and month.saving is not None:
        head += f"（月收入 {format_money(month.income)} − 需存 {format_money(month.saving)}）"
    head += f"；{spent}，"
    if month.short and month.left is not None:
        return head + f"已超 {format_money(-month.left)}"
    if month.left is not None:
        return head + f"还能花 {format_money(month.left)}"
    return head.rstrip("，") + _partial_note(month)


def _partial_note(month: MonthFacts) -> str:
    if month.partial and month.baseline_date:
        return f"（月初没有余额快照，从 {month.baseline_date[5:]} 起算）"
    return ""


def _pace_line(pace: PaceFacts) -> str:
    parts = [f"今日额度 {format_money(pace.quota)}（{pace.days} 天均摊）"]
    if pace.today is None:
        parts.append("今天还没记账")
    else:
        parts.append(f"今天花了 {format_money(pace.today)}")
    if pace.over:
        tail = f"超 {format_money(-pace.left)}"
        if pace.tomorrow is not None:
            tail += f"，明天降到 {format_money(pace.tomorrow)} 匀回来"
        parts.append(tail)
    else:
        tail = f"结余 {format_money(pace.left)}"
        if pace.tomorrow is not None:
            tail += f"，明天照 {format_money(pace.tomorrow)}"
        parts.append(tail)
    return "- " + " ｜ ".join(parts)


def _fact_notes(facts: Facts, *, prose_is_old: bool = False) -> list[str]:
    """把「这个数是怎么来的」写清楚：可疑、缺基线、补跑、只补了数字。

    `prose_is_old` 只在「素材已清理、只补事实」时为真——那时话确实不是这一轮写的。
    历史日重算（`--rebuild`）会连同话一起重写，不能说「话是当初写的」。
    """
    notes: list[str] = []
    if facts.balance.confidence == "suspect":
        notes.append("> 余额待确认：摘录对不上原文，这一笔先按观察到的用。")
    if facts.month is not None and facts.month.partial and facts.month.baseline_date:
        notes.append(
            f"> 月初没有余额快照，本月从 {facts.month.baseline_date[5:]} 起算，"
            "前面几天可能含上个月的尾巴。"
        )
    if facts.month is not None and (
        facts.month.spent is not None
        and facts.month.spent_as_of
        and facts.month.spent_as_of != facts.date
        and facts.month.left is None
    ):
        notes.append(f"> 今天没读到余额，已花算到 {facts.month.spent_as_of[5:]}。")
    if prose_is_old:
        notes.append("> 只补了数字，话是当初写的。")
    elif facts.backfilled:
        notes.append("> 补跑：数字按当前档案算，不是当天的档案。")
    return notes


__all__ = ["ConsoleChannel"]
