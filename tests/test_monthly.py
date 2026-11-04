"""当月累计：用月初/当前的余额快照相减，缺口不影响总额，但缺基线要标注。"""

from __future__ import annotations

import json
from pathlib import Path

from step_ledger.render.monthly import month_spend
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


def test_budget_is_optional(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-31": 12000, "2026-11-02": 11500})
    profile = parse_profile("- 目标：100 万\n- 约定：月度支出目标 = 3000\n", tmp_path / "p.md")

    result = month_spend(archive, "2026-11-02", profile)

    assert result is not None
    assert result.budget == 3000
    assert result.remaining == 2500


def test_no_archive_means_no_claim(tmp_path: Path) -> None:
    assert month_spend(tmp_path / "archive", "2026-11-02") is None
