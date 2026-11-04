"""当月累计 + 本月还能花多少。

当月累计用「月初前最后一个余额 − 当前余额」算：逐条加总短信里的「支取」会被笔笔攒
的两种写法（单独成条 / 并进余额差）和重复推送坑到，余额差不骗人。自动转存按支出算。

能花多少是倒推出来的，不用手填预算：

    月收入 − (每月需存 − 公积金月缴存) = 本月可花

「每月需存」由 `目标日期` 与当前缺口算出（见 `goal_plan`），公积金那部分不占现金。
剩多少 = 可花 − 已花，为负就是本月已经出现缺口。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

from ..shared.profile import Profile, goal_plan, parse_amount
from .trend import balances


@dataclass(frozen=True)
class MonthSpend:
    month: str          # 2026-11
    net_out: int        # 正数 = 卡里净流出（含自动转存）
    since: str          # 从哪一天的余额起算
    until: str          # 算到哪一天
    partial: bool       # 月初没有余额快照，只能从月中某天起算


@dataclass(frozen=True)
class SpendPlan:
    income: int          # 月到手收入
    saving: int          # 每月要从现金里存下的钱
    spendable: int       # 本月最多能花
    spent: int           # 本月已花

    @property
    def left(self) -> int:
        return self.spendable - self.spent

    @property
    def short(self) -> bool:
        return self.left < 0


def month_spend(archive_root: Path, day: str) -> MonthSpend | None:
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
    return MonthSpend(
        month=day[:7],
        net_out=found[since] - found[until],
        since=since,
        until=until,
        partial=partial,
    )


def spend_plan(profile: Profile | None, day: str, spent: int) -> SpendPlan | None:
    """月收入够不够撑住「按目标该存多少」，算完就知道这个月最多能花多少。"""
    if profile is None:
        return None
    income = parse_amount(profile.agreements.get("月收入"))
    plan = goal_plan(profile, day)
    if not income or plan is None:
        return None
    provident = parse_amount(profile.agreements.get("公积金月缴存")) or 0
    saving = max(plan.per_month - provident, 0)
    return SpendPlan(income=income, saving=saving, spendable=income - saving, spent=spent)


__all__ = ["MonthSpend", "SpendPlan", "month_spend", "spend_plan"]
