"""当月累计：用月初/当前的余额快照相减，缺口不影响总额，但缺基线要标注。"""

from __future__ import annotations

import json
from pathlib import Path

from step_ledger.render.monthly import day_spend, month_spend, pace, spend_plan
from step_ledger.shared.profile import parse_profile


def _archive(root: Path, days: dict[str, int | None]) -> Path:
    for day, balance in days.items():
        target = root / day
        target.mkdir(parents=True, exist_ok=True)
        (target / "judgment.json").write_text(
            json.dumps({"summary": "s", "advice": "a", "meta": {"date": day, "balance": balance}}),
            encoding="utf-8",
        )
    return root


def test_net_out_spans_month_start(tmp_path: Path) -> None:
    archive = _archive(
        tmp_path / "archive",
        {"2026-10-31": 12000, "2026-11-01": 11800, "2026-11-02": 11500},
    )

    result = month_spend(archive, "2026-11-02")

    assert result is not None
    assert result.net_out == 500  # 月初 12000 → 现在 11500
    assert result.since == "2026-10-31"
    assert result.until == "2026-11-02"
    assert result.partial is False


def test_missing_baseline_is_marked_partial(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-11-02": 11500, "2026-11-03": 11000})

    result = month_spend(archive, "2026-11-03")

    assert result is not None
    assert result.partial is True
    assert result.since == "2026-11-02"
    assert result.net_out == 500


def test_spend_plan_derives_from_income_and_goal(tmp_path: Path) -> None:
    """可花 = 月收入 −（每月需存 − 公积金月缴存）；不用手填预算。"""
    raw = (
        "- 目标：100 万\n- 当前存款：20 万\n"
        "- 约定：目标日期 = 2030-12\n- 约定：月收入 = 16000\n- 约定：公积金月缴存 = 3468\n"
    )
    profile = parse_profile(raw, tmp_path / "p.md")

    plan = spend_plan(profile, "2026-11-02", 200)

    assert plan is not None
    assert plan.saving == 16_327 - 3_468  # 每月需存里现金那部分
    assert plan.spendable == 16_000 - plan.saving
    assert plan.left == plan.spendable - 200
    assert plan.short is False


def test_spend_plan_needs_income(tmp_path: Path) -> None:
    profile = parse_profile("- 目标：100 万\n- 当前存款：20 万\n- 约定：目标日期 = 2030-12\n", tmp_path / "p.md")
    assert spend_plan(profile, "2026-11-02", 200) is None


def test_spend_plan_flags_shortfall(tmp_path: Path) -> None:
    raw = (
        "- 目标：100 万\n- 当前存款：20 万\n"
        "- 约定：目标日期 = 2026-12\n- 约定：月收入 = 16000\n"
    )
    profile = parse_profile(raw, tmp_path / "p.md")

    plan = spend_plan(profile, "2026-11-02", 30_000)

    assert plan is not None
    assert plan.short is True
    assert plan.left < 0


def test_no_archive_means_no_claim(tmp_path: Path) -> None:
    assert month_spend(tmp_path / "archive", "2026-11-02") is None


def test_pace_gives_daily_quota_and_tomorrow(tmp_path: Path) -> None:
    raw = (
        "- 目标：100 万\n- 当前存款：20 万\n"
        "- 约定：目标日期 = 2030-12\n- 约定：月收入 = 16000\n- 约定：公积金月缴存 = 3468\n"
    )
    profile = parse_profile(raw, tmp_path / "p.md")
    plan = spend_plan(profile, "2026-11-04", 220)

    p = pace(plan, "2026-11-04", 85)

    assert p.days == 30
    assert p.day_index == 4
    assert p.quota == round(plan.spendable / 30)
    assert p.allowed == round(plan.spendable * 4 / 30)
    assert p.left == p.allowed - 220
    assert p.over is False
    assert p.tomorrow == round((plan.spendable - 220) / 26)


def test_pace_flags_overspend_and_month_over(tmp_path: Path) -> None:
    raw = (
        "- 目标：100 万\n- 当前存款：20 万\n"
        "- 约定：目标日期 = 2030-12\n- 约定：月收入 = 16000\n- 约定：公积金月缴存 = 3468\n"
    )
    profile = parse_profile(raw, tmp_path / "p.md")
    plan = spend_plan(profile, "2026-11-04", 220)

    over = pace(spend_plan(profile, "2026-11-04", 1200), "2026-11-04", 900)
    blown = pace(spend_plan(profile, "2026-11-04", plan.spendable + 500), "2026-11-04", 0)

    assert over.over is True
    assert over.month_over is False
    assert over.tomorrow >= 0
    assert blown.month_over is True
    assert blown.tomorrow == 0


def test_day_spend_uses_previous_balance(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-11-02": 12000, "2026-11-03": 11800})

    assert day_spend(archive, "2026-11-03") == 200
    assert day_spend(archive, "2026-11-01") is None
