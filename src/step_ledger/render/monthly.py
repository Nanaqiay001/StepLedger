"""当月累计：用月初与当前的余额快照相减，得到「这个月卡里净出去多少」。

为什么不逐条加总短信里的「支取」：笔笔攒有时候单独成条、有时候并进余额差里，
重复推送的短信还会把同一笔算两遍。余额差不会骗人——它就是这个月卡里真实少了多少
（含自动转存出去的那部分）。口径写在报告里，不假装它是纯消费。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

from ..shared.profile import Profile, parse_amount
from .trend import balances


@dataclass(frozen=True)
class MonthSpend:
    month: str          # 2026-11
    net_out: int        # 正数 = 卡里净流出
    since: str          # 从哪一天的余额起算
    until: str          # 算到哪一天
    partial: bool       # 月初没有余额快照，只能从月中某天起算
    budget: int | None = None

    @property
    def remaining(self) -> int | None:
        return None if self.budget is None else self.budget - self.net_out


def month_spend(archive_root: Path, day: str, profile: Profile | None = None) -> MonthSpend | None:
    found = balances(archive_root)
    if not found:
        return None
    try:
        today = date_type.fromisoformat(day)
    except ValueError:
        return None
    month_start = today.replace(day=1).isoformat()
    within = sorted(d for d in found if month_start <= d <= day)
    if not within:
        return None
    until = within[-1]
    earlier = sorted(d for d in found if d < month_start)
    partial = not earlier
    since = earlier[-1] if earlier else within[0]
    budget = _budget(profile)
    return MonthSpend(
        month=day[:7],
        net_out=found[since] - found[until],
        since=since,
        until=until,
        partial=partial,
        budget=budget,
    )


def _budget(profile: Profile | None) -> int | None:
    if profile is None:
        return None
    for key in ("月度支出目标", "月度预算"):
        amount = parse_amount(profile.agreements.get(key))
        if amount:
            return amount
    return None


__all__ = ["MonthSpend", "month_spend"]
