"""趋势图：把判断层算好的余额序列落成 SVG + CSV。

这里只做画图，不读归档、不算余额——数据由 `judgment.trend.days` 带过来。
只用标准库和两种标准格式：SVG（W3C 矢量图，坐标精确、浏览器/预览器都能开）和
CSV（任何表格工具都能再画一次）。不引图表库，也不画字符画——字符画对齐靠字体，
换台机器就歪了。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..shared.types import DayPoint

WIDTH, HEIGHT = 760, 340
PAD_L, PAD_R, PAD_T, PAD_B = 64, 28, 44, 48


@dataclass(frozen=True)
class Point:
    day: str
    value: int | None


def to_csv(points: list[Point]) -> str:
    lines = ["date,balance"]
    lines += [f"{p.day},{'' if p.value is None else p.value}" for p in points]
    return "\n".join(lines) + "\n"


def to_svg(points: list[Point], title: str = "卡内余额") -> str:
    values = [p.value for p in points if p.value is not None]
    if not values:
        return _empty_svg(title)

    low, high = min(values), max(values)
    if high == low:
        high, low = high + 1, low - 1
    margin = max((high - low) * 0.12, 1)
    low, high = low - margin, high + margin

    plot_w = WIDTH - PAD_L - PAD_R
    plot_h = HEIGHT - PAD_T - PAD_B
    step_x = plot_w / max(len(points) - 1, 1)

    def x(index: int) -> float:
        return PAD_L + index * step_x

    def y(value: float) -> float:
        return PAD_T + (high - value) / (high - low) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="-apple-system, PingFang SC, sans-serif">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#fffef9"/>',
        f'<text x="{PAD_L}" y="26" font-size="15" fill="#3a3a3a">{title}</text>',
    ]
    for tick in range(5):
        value = high - (high - low) * tick / 4
        ty = y(value)
        parts.append(
            f'<line x1="{PAD_L}" y1="{ty:.1f}" x2="{WIDTH - PAD_R}" y2="{ty:.1f}" '
            f'stroke="#eee9dd" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{PAD_L - 10}" y="{ty + 4:.1f}" font-size="11" fill="#8a8577" '
            f'text-anchor="end">{_axis(value, high - low)}</text>'
        )

    runs, current = [], []
    for index, point in enumerate(points):
        if point.value is None:
            if current:
                runs.append(current)
            current = []
            continue
        current.append((x(index), y(point.value), point.value, point.day))
    if current:
        runs.append(current)

    for run in runs:
        coords = " ".join(f"{px:.1f},{py:.1f}" for px, py, _, _ in run)
        if len(run) > 1:
            parts.append(
                f'<polyline points="{coords}" fill="none" stroke="#c2703d" '
                f'stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>'
            )
        for px, py, value, day in run:
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.4" fill="#c2703d"/>')
            parts.append(f'<title>{day} ¥{value:,}</title>')

    for index in _label_indexes(len(points)):
        parts.append(
            f'<text x="{x(index):.1f}" y="{HEIGHT - PAD_B + 22}" font-size="11" '
            f'fill="#8a8577" text-anchor="middle">{points[index].day[5:]}</text>'
        )

    last = values[-1]
    parts.append(
        f'<text x="{WIDTH - PAD_R}" y="{PAD_T - 18}" font-size="12" fill="#c2703d" '
        f'text-anchor="end">最新 ¥{last:,}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write(days: list[DayPoint], target_dir: Path) -> list[Path]:
    """把 `trend.svg` 与 `trend.csv` 写进当天的归档目录，返回产物路径。"""
    points = [Point(day=day.day, value=day.balance) for day in days]
    if not any(point.value is not None for point in points):
        return []
    target_dir.mkdir(parents=True, exist_ok=True)
    svg_path = target_dir / "trend.svg"
    csv_path = target_dir / "trend.csv"
    svg_path.write_text(to_svg(points), encoding="utf-8")
    csv_path.write_text(to_csv(points), encoding="utf-8")
    return [svg_path, csv_path]


def _label_indexes(count: int) -> list[int]:
    if count <= 8:
        return list(range(count))
    stride = count // 7
    return sorted(set(list(range(0, count, stride)) + [count - 1]))


def _axis(value: float, span: float) -> str:
    """刻度标签：区间窄时保留一位小数，否则取整，避免几行都写成同一个 12k。"""
    if abs(value) < 10_000:
        return f"{int(round(value))}"
    return f"{value / 1000:.1f}k" if span < 4_000 else f"{int(round(value / 1000))}k"


def _empty_svg(title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="-apple-system, PingFang SC, sans-serif">'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#fffef9"/>'
        f'<text x="{WIDTH // 2}" y="{HEIGHT // 2}" font-size="13" fill="#8a8577" '
        f'text-anchor="middle">{title}：还没有可画的数据</text></svg>\n'
    )


__all__ = ["Point", "to_csv", "to_svg", "write"]
