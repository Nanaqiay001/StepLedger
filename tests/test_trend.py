"""趋势图：只吃判断层给的余额序列，缺口留空、不连成假线。"""

from __future__ import annotations

from pathlib import Path

from step_ledger.render import trend
from step_ledger.shared.types import DayPoint


def _points(values: dict[str, int | None]):
    return [trend.Point(day=day, value=value) for day, value in values.items()]


def test_svg_breaks_line_at_gap() -> None:
    points = _points({"2026-10-28": 12000, "2026-10-29": None, "2026-10-30": 11000})

    svg = trend.to_svg(points)

    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert svg.count("<circle") == 2  # 两个真实点
    assert "<polyline" not in svg  # 中间断开，不连成假线


def test_svg_connects_continuous_days() -> None:
    points = _points({"2026-10-28": 12000, "2026-10-29": 11500, "2026-10-30": 11000})

    svg = trend.to_svg(points)

    assert svg.count("<polyline") == 1
    assert svg.count("<circle") == 3


def test_csv_is_plain_two_columns() -> None:
    points = _points({"2026-10-28": 12000, "2026-10-29": None, "2026-10-30": 11000})

    rows = trend.to_csv(points).splitlines()

    assert rows[0] == "date,balance"
    assert rows[1] == "2026-10-28,12000"
    assert rows[2] == "2026-10-29,"  # 缺口留空，不是 0


def test_write_takes_day_points(tmp_path: Path) -> None:
    days = [
        DayPoint(day="2026-10-27", balance=12000),
        DayPoint(day="2026-10-28", balance=11000),
    ]

    written = trend.write(days, tmp_path / "out")

    assert [path.name for path in written] == ["trend.svg", "trend.csv"]
    assert (tmp_path / "out" / "trend.svg").read_text(encoding="utf-8").startswith("<svg")


def test_write_needs_data(tmp_path: Path) -> None:
    assert trend.write([DayPoint(day="2026-10-28", balance=None)], tmp_path / "out") == []
    assert not (tmp_path / "out" / "trend.svg").exists()


def test_empty_svg_says_no_data() -> None:
    assert "还没有可画的数据" in trend.to_svg([])
