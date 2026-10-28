"""profile.md 的解析与默认值。"""

from __future__ import annotations

from pathlib import Path

import pytest

from step_ledger.shared.profile import (
    ensure_profile,
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
