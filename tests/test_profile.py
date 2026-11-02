"""profile.md 的解析与默认值。"""

from __future__ import annotations

from pathlib import Path

import pytest

from step_ledger.shared.profile import (
    ensure_profile,
    goal_plan,
    load_profile,
    parse_amount,
    parse_profile,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("100 万", 1_000_000),
        ("12.5万", 125_000),
        ("1,200", 1_200),
        ("¥88", 88),
        ("3k", 3_000),
        ("", None),
        ("没写", None),
    ],
)
def test_parse_amount(text: str, expected: int | None) -> None:
    assert parse_amount(text) == expected


def test_parse_profile_fields(tmp_path: Path) -> None:
    profile = parse_profile(
        "# 档案\n\n- 目标：100 万\n- 当前存款：120,000\n- 提醒时间：21:30\n- 偏好：别啰嗦\n",
        tmp_path / "profile.md",
    )
    assert profile.target == 1_000_000
    assert profile.savings == 120_000
    assert profile.distance == 880_000
    assert profile.percent == pytest.approx(0.12)
    assert profile.preferred_time == "21:30"


def test_missing_profile_uses_defaults(tmp_path: Path) -> None:
    profile = load_profile(tmp_path / "profile.md")
    assert profile.exists is False
    assert profile.target == 1_000_000
    assert profile.savings is None
    assert profile.distance is None


def test_ensure_profile_creates_template(tmp_path: Path) -> None:
    path = tmp_path / "materials" / "profile.md"
    profile = ensure_profile(path)
    assert path.is_file()
    assert profile.created is True
    assert profile.target == 1_000_000

    again = ensure_profile(path)
    assert again.created is False


def test_agreements_split_kv_and_prose(tmp_path: Path) -> None:
    """`键 = 值` 进结构化约定（代码能用），其余原话进 notes（只给模型读）。"""
    raw = (
        "- 目标：100 万\n"
        "- 约定：目标日期 = 2030-12\n"
        "- 约定：工资到账日 = 每月 11 号\n"
        "- 约定：这笔钱算存钱不算花销\n"
    )

    profile = parse_profile(raw, tmp_path / "profile.md")

    assert profile.agreements["目标日期"] == "2030-12"
    assert profile.agreements["工资到账日"] == "每月 11 号"
    assert profile.notes == ["这笔钱算存钱不算花销"]


def test_goal_plan_counts_months_and_monthly_amount(tmp_path: Path) -> None:
    raw = "- 目标：100 万\n- 当前存款：20 万\n- 约定：目标日期 = 2030-12\n"
    profile = parse_profile(raw, tmp_path / "profile.md")

    plan = goal_plan(profile, "2026-11-02")

    assert plan is not None
    assert plan.deadline == "2030-12"
    assert plan.months == 49
    assert plan.per_month == 16_327  # 800,000 / 49，向上取整


def test_goal_plan_needs_deadline_and_savings(tmp_path: Path) -> None:
    no_deadline = parse_profile("- 目标：100 万\n- 当前存款：20 万\n", tmp_path / "p.md")
    no_savings = parse_profile("- 目标：100 万\n- 约定：目标日期 = 2030-12\n", tmp_path / "p.md")
    past = parse_profile(
        "- 目标：100 万\n- 当前存款：20 万\n- 约定：目标日期 = 2025-12\n", tmp_path / "p.md"
    )

    assert goal_plan(no_deadline, "2026-11-02") is None
    assert goal_plan(no_savings, "2026-11-02") is None
    assert goal_plan(past, "2026-11-02") is None
