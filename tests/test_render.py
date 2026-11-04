"""渲染层：只排版。报告前三行、目标进度、当月累计、里程碑、各种标注。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from step_ledger.render.channels.console import ConsoleChannel
from step_ledger.shared.types import (
    DayPoint,
    Facts,
    GoalFacts,
    Judgment,
    MonthFacts,
    PaceFacts,
    ProgressPoint,
    RenderContext,
    TrendSummary,
)


def _ctx(tmp_path: Path) -> RenderContext:
    return RenderContext(out_dir=tmp_path / "archive" / "2026-10-28", echo=False)


def _facts(**overrides) -> Facts:
    base = Facts(
        date="2026-10-28",
        goal=GoalFacts(
            target=1_000_000,
            savings=200_000,
            savings_source="profile",
            distance=800_000,
            percent=0.2,
        ),
        month=MonthFacts(
            key="2026-10",
            baseline_date="2026-09-30",
            baseline=120_000,
            spent=300,
            spent_as_of="2026-10-28",
            income=20_000,
            saving=16_000,
            spendable=4_000,
            left=3_700,
        ),
        pace=PaceFacts(days=31, index=28, quota=129, allowed=3613, today=100, left=3313, tomorrow=129),
    )
    return replace(base, **overrides)


def _goal(**changes):
    return replace(_facts().goal, **changes)


def _month(**changes):
    return replace(_facts().month, **changes)


def _pace(**changes):
    return replace(_facts().pace, **changes)


def _judgment(**overrides) -> Judgment:
    payload = dict(summary="这两天挺稳的。", advice="明天少点一次外卖。", facts=_facts())
    payload.update(overrides)
    return Judgment(**payload)


def test_report_and_milestones(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    trend = TrendSummary(days=[DayPoint(day="2026-10-27", balance=12000)])
    judgment = _judgment(trend=trend)

    result = ConsoleChannel().render(judgment, ctx)

    report = (ctx.out_dir / "report.md").read_text(encoding="utf-8")
    assert report.splitlines()[1].startswith("最近怎么样：")
    assert report.splitlines()[2].startswith("下一步怎么走：")
    assert "20.0%" in report
    assert "本月可花：¥4,000" in report
    assert "今日额度 ¥129" in report
    names = [path.name for path in result.artifacts]
    assert {"report.md", "milestones.md", "trend.svg", "trend.csv"} <= set(names)

    milestones = (ctx.out_dir / "milestones.md").read_text(encoding="utf-8")
    assert "目标里程碑" in milestones


def test_milestones_collects_history(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    trend = TrendSummary(progress=[ProgressPoint(day="2026-10-27", savings=100_000, percent=0.1)])

    ConsoleChannel().render(_judgment(trend=trend), ctx)

    milestones = (ctx.out_dir / "milestones.md").read_text(encoding="utf-8")
    assert "2026-10-27" in milestones
    assert "10.0%" in milestones


def test_degraded_is_labelled(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    ConsoleChannel().render(_judgment(degraded=True), ctx)

    assert "降级模式" in (ctx.out_dir / "report.md").read_text(encoding="utf-8")


def test_missing_savings_still_renders(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    facts = _facts(
        goal=_goal(savings=None, savings_source="none", distance=None, percent=None)
    )

    ConsoleChannel().render(_judgment(facts=facts, runtime={"profile_created": True}), ctx)

    report = (ctx.out_dir / "report.md").read_text(encoding="utf-8")
    assert "第一次见" in report
    assert "暂时画不出进度条" in report


def test_report_shows_goal_deadline(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    facts = _facts(goal=_goal(deadline="2030-12", months=50, per_month=16_000))

    report = ConsoleChannel().render(_judgment(facts=facts), ctx).output

    assert "目标日期：2030-12" in report
    assert "还剩 50 个月" in report
    assert "每月要存 ¥16,000" in report


def test_month_line_says_how_much_left(tmp_path: Path) -> None:
    report = ConsoleChannel().render(_judgment(), _ctx(tmp_path)).output

    assert "本月可花：¥4,000" in report
    assert "已花 ¥300" in report
    assert "还能花 ¥3,700" in report


def test_month_over_is_stated(tmp_path: Path) -> None:
    facts = _facts(month=_month(spent=4_500, left=-500, short=True))

    report = ConsoleChannel().render(_judgment(facts=facts), _ctx(tmp_path)).output

    assert "已超 ¥500" in report


def test_pace_over_says_what_tomorrow_should_be(tmp_path: Path) -> None:
    facts = _facts(pace=_pace(over=True, left=-20, tomorrow=120))

    report = ConsoleChannel().render(_judgment(facts=facts), _ctx(tmp_path)).output

    assert "明天降到 ¥120 匀回来" in report


def test_suspect_balance_is_flagged(tmp_path: Path) -> None:
    facts = _facts(balance=replace(_facts().balance, confidence="suspect", value=11_000))

    report = ConsoleChannel().render(_judgment(facts=facts), _ctx(tmp_path)).output

    assert "余额待确认" in report


def test_backfilled_facts_say_numbers_use_current_profile(tmp_path: Path) -> None:
    facts = _facts(backfilled=True)

    report = ConsoleChannel().render(_judgment(facts=facts), _ctx(tmp_path)).output

    assert "补跑" in report
    assert "不是当天的档案" in report
    assert "话是当初写的" not in report  # 这一天连同话一起重算过，不能这么说


def test_facts_only_backfill_says_prose_is_old(tmp_path: Path) -> None:
    facts = _facts(backfilled=True)

    report = ConsoleChannel().render(
        _judgment(facts=facts, runtime={"facts_backfilled": True}), _ctx(tmp_path)
    ).output

    assert "只补了数字" in report
    assert "话是当初写的" in report


def test_report_without_facts_still_renders(tmp_path: Path) -> None:
    """旧的判断结果（没有事实快照）不该让渠道崩掉。"""
    ctx = _ctx(tmp_path)

    report = ConsoleChannel().render(Judgment(summary="稳", advice="继续"), ctx).output

    assert "最近怎么样：稳" in report
    assert "未填写" in report


def test_first_day_says_no_earlier_balance(tmp_path: Path) -> None:
    """第一天只有一条余额，已花量不出来——别把它说成「没有余额」。"""
    facts = _facts(
        month=replace(
            _facts().month,
            baseline=None,
            spent=None,
            spent_as_of=None,
            left=None,
            partial=True,
        )
    )

    report = ConsoleChannel().render(_judgment(facts=facts), _ctx(tmp_path)).output

    assert "月初还没有更早的余额" in report


def test_echo_points_at_the_chart(tmp_path: Path, capsys) -> None:
    """终端输出里要提一句图表在哪，否则没人知道它生成了。"""
    ctx = _ctx(tmp_path)
    ctx.echo = True
    trend = TrendSummary(days=[DayPoint(day="2026-10-28", balance=11000)])

    ConsoleChannel().render(_judgment(trend=trend), ctx)

    out = capsys.readouterr().out
    assert "图表：" in out
    assert "trend.svg" in out


def test_no_chart_no_line(tmp_path: Path, capsys) -> None:
    ctx = _ctx(tmp_path)
    ctx.echo = True

    ConsoleChannel().render(_judgment(), ctx)  # 没有余额点，不画图

    assert "图表：" not in capsys.readouterr().out
