"""把「观测」算成「事实」。这里是判断层唯一的算术位置。

纯函数：不调模型、不读文件、不看时钟。给定同样的输入永远输出同样的结果，
所以可以断点重放、可以单测、可以在补跑时逐个日期重算。

口径（与 `docs/rfc.md` 一致）：

- 已花 = 月初前最后一个余额 − 当天余额（余额差不骗人，不逐条加总短信）
- 可花 = 月收入 − (每月需存 − 公积金月缴存)，每月需存由目标日期与缺口倒推
- 日额度 = 可花 ÷ 当月天数；明天额度 = (可花 − 已花) ÷ 剩余天数
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date as date_type
from datetime import timedelta
from math import ceil

from ..shared.profile import Profile, months_until, parse_amount
from ..shared.types import (
    BalanceObs,
    DayPoint,
    Facts,
    GoalFacts,
    MonthFacts,
    Observation,
    PaceFacts,
    ProgressPoint,
    TrendSummary,
)
from .history import History

WINDOW_DAYS = 14


def compute(
    *,
    day: str,
    profile: Profile,
    observation: Observation,
    history: History,
    backfilled: bool = False,
) -> Facts:
    """一天的事实快照。`backfilled` 只用于标注「数字按当前档案算」。"""
    balance = observation.balance
    savings, source = _savings(profile, balance)
    distance = max(profile.target - savings, 0) if savings is not None else None
    percent = None
    if savings is not None and profile.target > 0:
        percent = min(max(savings / profile.target, 0.0), 1.0)

    deadline, months = _deadline(profile, day)
    per_month = ceil(distance / months) if distance is not None and months else None
    goal = GoalFacts(
        target=profile.target,
        savings=savings,
        savings_source=source,
        distance=distance,
        percent=percent,
        deadline=deadline,
        months=months,
        per_month=per_month,
    )

    month = _month(
        day=day,
        profile=profile,
        balance=balance,
        distance=distance,
        months=months,
        history=history,
    )
    pace = _pace(day=day, month=month, balance=balance, history=history)
    return Facts(
        date=day,
        backfilled=backfilled,
        balance=balance,
        goal=goal,
        month=month,
        pace=pace,
    )


def summarize_trend(
    *,
    day: str,
    history: History,
    facts: Facts,
    window: int = WINDOW_DAYS,
) -> TrendSummary:
    """近两周的每日花销 + 周环比 + 超支天数 + 最低余额 + 进度历史。"""
    try:
        end = date_type.fromisoformat(day)
    except ValueError:
        return TrendSummary()
    start = end - timedelta(days=window - 1)
    start_text = start.isoformat()

    balances = history.balances_in(start_text, day)
    if facts.balance.value is not None:
        as_of = facts.balance.as_of or day
        if start_text <= as_of <= day:
            balances[as_of] = facts.balance.value

    spent = _spent_by_day(balances)
    quota = facts.pace.quota if facts.pace is not None else None
    month_key = facts.month.key if facts.month is not None else None

    points: list[DayPoint] = []
    for offset in range(window):
        current = (start + timedelta(days=offset)).isoformat()
        daily = spent.get(current)
        day_quota = quota if quota is not None and month_key == current[:7] else None
        points.append(
            DayPoint(
                day=current,
                spent=daily,
                quota=day_quota,
                over=bool(day_quota is not None and daily is not None and daily > day_quota),
            )
        )

    week = [point for point in points if point.day >= (end - timedelta(days=6)).isoformat()]
    previous = [
        point
        for point in points
        if (end - timedelta(days=13)).isoformat() <= point.day <= (end - timedelta(days=7)).isoformat()
    ]
    progress = history.progress_in(start_text, (end - timedelta(days=1)).isoformat())
    if facts.goal.savings is not None or facts.goal.percent is not None:
        progress.append(ProgressPoint(day=day, savings=facts.goal.savings, percent=facts.goal.percent))

    return TrendSummary(
        days=points,
        week_spent=_total(week),
        prev_week_spent=_total(previous),
        over_days=sum(1 for point in week if point.over),
        balance_low=min(balances.values()) if balances else None,
        progress=progress,
    )


def _savings(profile: Profile, balance: BalanceObs) -> tuple[int | None, str]:
    """手填存款优先；没填才用当天余额兜底，并标明来源。"""
    if profile.savings is not None:
        return profile.savings, "profile"
    if balance.value is not None:
        return balance.value, "balance"
    return None, "none"


def _deadline(profile: Profile, day: str) -> tuple[str | None, int | None]:
    found = months_until(profile.agreements, day)
    return found if found else (None, None)


def _month(
    *,
    day: str,
    profile: Profile,
    balance: BalanceObs,
    distance: int | None,
    months: int | None,
    history: History,
) -> MonthFacts | None:
    try:
        today = date_type.fromisoformat(day)
    except ValueError:
        return None
    month_start = today.replace(day=1).isoformat()

    baseline_date, baseline = None, None
    before = history.last_balance_before(month_start)
    partial = before is None
    if before is not None:
        baseline_date, baseline = before
    else:
        within = history.balances_in(month_start, day)
        if within:
            baseline_date = min(within)
            baseline = within[baseline_date]

    spent_as_of, current = _current_balance(day=day, balance=balance, history=history)
    spent = None
    if (
        baseline is not None
        and current is not None
        and baseline_date is not None
        and spent_as_of is not None
        and spent_as_of > baseline_date
    ):
        spent = baseline - current

    income = parse_amount(profile.agreements.get("月收入"))
    provident = parse_amount(profile.agreements.get("公积金月缴存")) or 0
    saving = spendable = None
    if income is not None and distance is not None and months:
        saving = max(ceil(distance / months) - provident, 0)
        spendable = income - saving

    left = spendable - spent if spendable is not None and spent is not None else None
    return MonthFacts(
        key=day[:7],
        baseline_date=baseline_date,
        baseline=baseline,
        partial=partial,
        spent=spent,
        spent_as_of=spent_as_of,
        income=income,
        saving=saving,
        spendable=spendable,
        left=left,
        short=bool(left is not None and left < 0),
    )


def _current_balance(
    *, day: str, balance: BalanceObs, history: History
) -> tuple[str | None, int | None]:
    """当天余额优先；读不到就退回「上一个有余额的日子」，并如实回报是哪天。"""
    if balance.value is not None:
        return (balance.as_of or day), balance.value
    previous = history.last_balance_before(day)
    if previous is None:
        return None, None
    return previous


def _pace(*, day: str, month: MonthFacts | None, balance: BalanceObs, history: History) -> PaceFacts | None:
    if month is None or month.spendable is None or month.spent is None:
        return None
    try:
        today = date_type.fromisoformat(day)
    except ValueError:
        return None
    days = monthrange(today.year, today.month)[1]
    index = today.day
    quota = round(month.spendable / days)
    allowed = round(month.spendable * index / days)
    left = allowed - month.spent
    rest = days - index
    tomorrow = max(round((month.spendable - month.spent) / rest), 0) if rest > 0 else None

    today_spent = None
    if balance.value is not None and (balance.as_of or day) == day:
        previous = history.last_balance_before(day)
        if previous is not None:
            today_spent = previous[1] - balance.value

    return PaceFacts(
        days=days,
        index=index,
        quota=quota,
        allowed=allowed,
        today=today_spent,
        left=left,
        over=left < 0,
        tomorrow=tomorrow,
    )


def _spent_by_day(balances: dict[str, int]) -> dict[str, int]:
    """相邻两个已知余额的差，记在后一个日期上；空档不插值。"""
    known = sorted(balances)
    spent: dict[str, int] = {}
    for index in range(1, len(known)):
        previous, current = known[index - 1], known[index]
        spent[current] = balances[previous] - balances[current]
    return spent


def _total(points: list[DayPoint]) -> int | None:
    known = [point.spent for point in points if point.spent is not None]
    return sum(known) if known else None


__all__ = ["WINDOW_DAYS", "compute", "summarize_trend"]
