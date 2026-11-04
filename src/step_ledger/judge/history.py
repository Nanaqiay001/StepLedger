"""只读历史：把 `archive/<日期>/judgment.json` 当成一本编年史。

两条硬约束，靠接口而不是靠自觉：

1. **只读 `<= 构造日` 的数据**，补跑历史日期看不到未来
2. **余额序列排除当天自身**：今天的余额只来自 `observation`，不来自今天已经写过的
   结果。否则同一天重跑会拿自己上一轮当历史，`compute()` 就不再是纯函数

旧归档（只有 `meta.balance`、没有 `facts`）按天降级读取，`legacy` 标记出来。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..shared.types import ProgressPoint, facts_from_dict


@dataclass(frozen=True)
class DayRecord:
    """归档里的一天。余额按 `as_of` 记，进度按目录日期记。"""

    day: str
    balance: int | None = None
    balance_as_of: str | None = None
    savings: int | None = None
    percent: float | None = None
    legacy: bool = False


class History:
    """某一天之前（含当天）的归档视图。构造时就把数据读齐，之后只做查询。"""

    def __init__(self, archive_root: Path, *, day: str) -> None:
        self.archive_root = Path(archive_root)
        self.day = day
        self.records = _load(self.archive_root, day)

    def last_balance_before(self, day: str) -> tuple[str, int] | None:
        """`day` 之前最后一个已知余额（严格小于）。没有就返回 None，不猜。"""
        found = [(as_of, value) for as_of, value in self._balances().items() if as_of < day]
        return max(found) if found else None

    def balances_in(self, start: str, end: str) -> dict[str, int]:
        """区间内的余额快照，键是余额自己的日期（可能比归档日早）。"""
        return {
            as_of: value
            for as_of, value in self._balances().items()
            if start <= as_of <= end
        }

    def progress_in(self, start: str, end: str) -> list[ProgressPoint]:
        """区间内的进度点，供里程碑使用；没有进度的日子不出现。"""
        return [
            ProgressPoint(day=record.day, savings=record.savings, percent=record.percent)
            for record in self.records
            if start <= record.day <= end
            and (record.savings is not None or record.percent is not None)
        ]

    def _balances(self) -> dict[str, int]:
        """余额序列：排除当天自身，且不采纳「归到未来」的余额。"""
        balances: dict[str, int] = {}
        for record in self.records:
            if record.day >= self.day or record.balance is None:
                continue
            as_of = record.balance_as_of or record.day
            if as_of >= self.day:
                continue
            balances[as_of] = record.balance
        return balances


def _load(root: Path, day: str) -> list[DayRecord]:
    if not root.is_dir():
        return []
    records: list[DayRecord] = []
    for day_dir in sorted(root.iterdir()):
        name = day_dir.name
        if not _is_date(name) or name > day or not day_dir.is_dir():
            continue
        path = day_dir / "judgment.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        records.append(_record(name, data))
    return records


def _record(name: str, data: dict[str, Any]) -> DayRecord:
    facts = facts_from_dict(data.get("facts"))
    if facts is not None:
        return DayRecord(
            day=name,
            balance=facts.balance.value,
            balance_as_of=facts.balance.as_of or name,
            savings=facts.goal.savings,
            percent=facts.goal.percent,
        )
    # 旧归档：meta.balance / meta.progress
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    progress = meta.get("progress") if isinstance(meta.get("progress"), dict) else {}
    return DayRecord(
        day=name,
        balance=_number(meta.get("balance")),
        balance_as_of=name,
        savings=_number(progress.get("savings")),
        percent=_fraction(progress.get("percent")),
        legacy=True,
    )


def _is_date(name: str) -> bool:
    return len(name) == 10 and name[4] == "-" and name[7] == "-"


def _number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _fraction(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["DayRecord", "History"]
