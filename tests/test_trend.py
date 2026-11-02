"""趋势图：余额序列（缺口要留空）、SVG 与 CSV 两种标准产物。"""

from __future__ import annotations

import json
from pathlib import Path

from step_ledger.render import trend


def _archive(root: Path, days: dict[str, int | None]) -> Path:
    for day, balance in days.items():
        target = root / day
        target.mkdir(parents=True, exist_ok=True)
        meta = {"date": day, "balance": balance}
        (target / "judgment.json").write_text(
            json.dumps({"summary": "s", "advice": "a", "meta": meta}), encoding="utf-8"
        )
    return root


def test_series_keeps_gaps_instead_of_zero(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-28": 12000, "2026-10-30": 11000})

    points = trend.series(archive)

    assert [p.day for p in points] == ["2026-10-28", "2026-10-29", "2026-10-30"]
    assert [p.value for p in points] == [12000, None, 11000]


def test_series_ignores_days_without_balance(tmp_path: Path) -> None:
    """当天没读到余额（空素材日）不算数据点，也不该把窗口撑长。"""
    archive = _archive(tmp_path / "archive", {"2026-10-28": 12000, "2026-10-29": None})

    points = trend.series(archive)

    assert [p.day for p in points] == ["2026-10-28"]


def test_series_trims_window_to_data(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-28": 12000, "2026-11-02": 11000})

    points = trend.series(archive)

    assert len(points) == 6
    assert points[0].day == "2026-10-28"
    assert points[-1].day == "2026-11-02"


def test_svg_breaks_line_at_gap(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-28": 12000, "2026-10-29": None, "2026-10-30": 11000})

    svg = trend.to_svg(trend.series(archive))

    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert svg.count("<circle") == 2  # 两个真实点
    assert "<polyline" not in svg  # 中间断开，不连成假线


def test_svg_connects_continuous_days(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-28": 12000, "2026-10-29": 11500, "2026-10-30": 11000})

    svg = trend.to_svg(trend.series(archive))

    assert svg.count("<polyline") == 1
    assert svg.count("<circle") == 3


def test_csv_is_plain_two_columns(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-28": 12000, "2026-10-30": 11000})

    rows = trend.to_csv(trend.series(archive)).splitlines()

    assert rows[0] == "date,balance"
    assert rows[1] == "2026-10-28,12000"
    assert rows[2] == "2026-10-29,"  # 缺口留空，不是 0


def test_write_needs_data(tmp_path: Path) -> None:
    assert trend.write(tmp_path / "empty", tmp_path / "out") == []
    assert not (tmp_path / "out" / "trend.svg").exists()


def test_empty_svg_says_no_data() -> None:
    assert "还没有可画的数据" in trend.to_svg([])
