"""事实层：余额序列 → 已花 / 可花 / 日额度，以及历史趋势统计。

这些数由代码算，模型不参与；所以测试直接断言数字，不用 mock 任何东西。
"""

from __future__ import annotations

import json
from pathlib import Path

from step_ledger.judge.facts import compute, summarize_trend
from step_ledger.judge.history import History
from step_ledger.shared.profile import parse_profile
from step_ledger.shared.types import BalanceObs, Facts, Observation

DAY = "2026-11-04"


def _archive(root: Path, days: dict[str, int | None]) -> Path:
    """旧归档格式（只有 meta.balance），顺带覆盖 legacy 读取路径。"""
    for day, balance in days.items():
        target = root / day
        target.mkdir(parents=True, exist_ok=True)
        (target / "judgment.json").write_text(
            json.dumps({"summary": "s", "advice": "a", "meta": {"date": day, "balance": balance}}),
            encoding="utf-8",
        )
    return root


def _profile(
    tmp_path: Path,
    *,
    savings: str | None = "20 万",
    income: str | None = "16000",
    provident: str | None = "3468",
    deadline: str | None = "2030-12",
) -> object:
    raw = "- 目标：100 万\n"
    if savings:
        raw += f"- 当前存款：{savings}\n"
    if deadline:
        raw += f"- 约定：目标日期 = {deadline}\n"
    if income:
        raw += f"- 约定：月收入 = {income}\n"
    if provident:
        raw += f"- 约定：公积金月缴存 = {provident}\n"
    return parse_profile(raw, tmp_path / "profile.md")


def _obs(value: int | None, as_of: str | None = DAY) -> Observation:
    return Observation(balance=BalanceObs(value=value, as_of=as_of, excerpt="交易后余额", confidence="ok"))


def _facts(tmp_path: Path, days: dict[str, int | None], **kwargs) -> Facts:
    archive = _archive(tmp_path / "archive", days)
    return compute(
        day=DAY,
        profile=_profile(tmp_path, **kwargs),
        observation=_obs(11400),
        history=History(archive, day=DAY),
    )


# ── 历史读取 ────────────────────────────────────────────────────


def test_history_ignores_future_days(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-11-03": 11500, "2026-11-05": 9000})

    history = History(archive, day=DAY)

    assert history.last_balance_before(DAY) == ("2026-11-03", 11500)


def test_history_excludes_the_day_itself(tmp_path: Path) -> None:
    """今天的余额只能来自观测；否则同日重跑会拿自己上一轮当历史。"""
    archive = _archive(tmp_path / "archive", {"2026-11-03": 11500, DAY: 99999})

    history = History(archive, day=DAY)

    assert history.last_balance_before(DAY) == ("2026-11-03", 11500)
    assert DAY not in history.balances_in("2026-11-01", DAY)


def test_history_skips_broken_and_unrelated_dirs(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    _archive(archive, {"2026-11-03": 11500})
    broken = archive / "2026-11-02"
    broken.mkdir(parents=True)
    (broken / "judgment.json").write_text("{", encoding="utf-8")
    (archive / "state").mkdir()
    (archive / "strategy.json").write_text("{}", encoding="utf-8")

    history = History(archive, day=DAY)

    assert [record.day for record in history.records] == ["2026-11-03"]


# ── 计算 ────────────────────────────────────────────────────────


def test_spent_uses_last_balance_before_month_start(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {"2026-10-31": 12000, "2026-11-03": 11500})

    assert facts.month is not None
    assert facts.month.baseline_date == "2026-10-31"
    assert facts.month.baseline == 12000
    assert facts.month.spent == 600  # 12000 − 11400
    assert facts.month.spent_as_of == DAY
    assert facts.month.partial is False


def test_missing_month_baseline_falls_back_to_first_known_balance(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {"2026-11-02": 11500, "2026-11-03": 11450})

    assert facts.month is not None
    assert facts.month.partial is True
    assert facts.month.baseline_date == "2026-11-02"
    assert facts.month.spent == 100  # 11500 − 11400


def test_spent_is_unknown_without_any_balance(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {})

    facts = compute(
        day=DAY,
        profile=_profile(tmp_path),
        observation=_obs(None, as_of=None),
        history=History(archive, day=DAY),
    )

    assert facts.month is not None
    assert facts.month.spent is None
    assert facts.month.spent_as_of is None
    assert facts.pace is None


def test_spent_falls_back_to_previous_balance_and_says_so(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-31": 12000, "2026-11-03": 11500})

    facts = compute(
        day=DAY,
        profile=_profile(tmp_path),
        observation=_obs(None, as_of=None),
        history=History(archive, day=DAY),
    )

    assert facts.month is not None
    assert facts.month.spent == 500  # 12000 − 11500
    assert facts.month.spent_as_of == "2026-11-03"
    assert facts.pace is not None
    assert facts.pace.today is None  # 今天没读到余额，就不假装今天花了 0


def test_goal_prefers_profile_savings_then_balance(tmp_path: Path) -> None:
    from_profile = _facts(tmp_path, {})
    assert from_profile.goal.savings == 200_000
    assert from_profile.goal.savings_source == "profile"

    other = tmp_path / "other"
    other.mkdir()
    from_balance = compute(
        day=DAY,
        profile=_profile(other, savings=None),
        observation=_obs(11400),
        history=History(_archive(other / "archive", {}), day=DAY),
    )
    assert from_balance.goal.savings == 11400
    assert from_balance.goal.savings_source == "balance"


def test_goal_plan_matches_monthly_cost(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {})

    assert facts.goal.distance == 800_000
    assert facts.goal.months == 49  # 2026-11 → 2030-12
    assert facts.goal.per_month == 16_327
    assert facts.goal.percent == 0.2


def test_spendable_is_income_minus_cash_saving(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {})

    assert facts.month is not None
    assert facts.month.saving == 16_327 - 3_468
    assert facts.month.spendable == 16_000 - (16_327 - 3_468)


def test_spendable_needs_income(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {}, income=None)

    assert facts.month is not None
    assert facts.month.spendable is None
    assert facts.month.left is None
    assert facts.pace is None


def test_pace_splits_spendable_across_days(tmp_path: Path) -> None:
    facts = _facts(tmp_path, {"2026-10-31": 12000, "2026-11-03": 11500})

    assert facts.pace is not None
    assert facts.pace.days == 30
    assert facts.pace.index == 4
    assert facts.pace.quota == round(3141 / 30)  # 105
    assert facts.pace.allowed == round(3141 * 4 / 30)  # 419
    assert facts.pace.left == 419 - 600
    assert facts.pace.over is True
    assert facts.pace.today == 100  # 11500 → 11400
    assert facts.pace.tomorrow == max(round((3141 - 600) / 26), 0)


def test_month_over_when_spent_exceeds_spendable(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-31": 16000})

    facts = compute(
        day=DAY,
        profile=_profile(tmp_path),
        observation=_obs(11000, as_of=DAY),
        history=History(archive, day=DAY),
    )

    assert facts.month is not None
    assert facts.month.spent == 5000
    assert facts.month.left == 3141 - 5000
    assert facts.month.short is True


def test_backfilled_flag_is_carried(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-31": 12000})

    facts = compute(
        day=DAY,
        profile=_profile(tmp_path),
        observation=_obs(11400),
        history=History(archive, day=DAY),
        backfilled=True,
    )

    assert facts.backfilled is True


def test_compute_is_a_pure_function(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {"2026-10-31": 12000, "2026-11-03": 11500})
    profile = _profile(tmp_path)

    first = compute(day=DAY, profile=profile, observation=_obs(11400), history=History(archive, day=DAY))
    second = compute(day=DAY, profile=profile, observation=_obs(11400), history=History(archive, day=DAY))

    assert first == second


# ── 趋势 ────────────────────────────────────────────────────────


def _trend(tmp_path: Path) -> object:
    facts = _facts(tmp_path, {"2026-10-31": 12000, "2026-11-01": 11800, "2026-11-03": 11500})
    archive = tmp_path / "archive"
    return summarize_trend(day=DAY, history=History(archive, day=DAY), facts=facts, window=14)


def test_trend_covers_calendar_window_with_gaps(tmp_path: Path) -> None:
    trend = _trend(tmp_path)

    assert len(trend.days) == 14
    assert trend.days[-1].day == DAY
    assert trend.days[0].day == "2026-10-22"
    by_day = {point.day: point for point in trend.days}
    assert by_day["2026-11-01"].spent == 200  # 12000 → 11800
    assert by_day["2026-11-02"].spent is None  # 空档不插值
    assert by_day["2026-11-03"].spent == 300  # 11800 → 11500
    assert by_day[DAY].spent == 100  # 11500 → 11400（今天的观测）


def test_trend_weekly_totals_and_over_days(tmp_path: Path) -> None:
    trend = _trend(tmp_path)

    assert trend.week_spent == 600  # 200 + 300 + 100
    assert trend.prev_week_spent is None  # 前一周没有可比的余额差
    assert trend.over_days == 2  # 200 和 300 都超了日额度 105
    assert trend.balance_low == 11400


def test_trend_marks_today_on_progress(tmp_path: Path) -> None:
    trend = _trend(tmp_path)

    assert trend.progress[-1].day == DAY
    assert trend.progress[-1].savings == 200_000


def test_trend_survives_invalid_day(tmp_path: Path) -> None:
    archive = _archive(tmp_path / "archive", {})
    facts = compute(
        day=DAY,
        profile=_profile(tmp_path),
        observation=_obs(None),
        history=History(archive, day=DAY),
    )

    trend = summarize_trend(day="not-a-date", history=History(archive, day=DAY), facts=facts)

    assert trend.days == []


def test_salary_inflow_is_not_spending(tmp_path: Path) -> None:
    """工资打进这张卡时，余额差会变成负数；按约定把入账扣掉，剩下的才是花销。"""
    raw = (
        "- 目标：100 万\n- 当前存款：20 万\n"
        "- 约定：目标日期 = 2030-12\n- 约定：月收入 = 16831\n"
        "- 约定：工资到账日 = 每月 11 号\n"
    )
    profile = parse_profile(raw, tmp_path / "profile.md")
    archive = _archive(tmp_path / "archive", {"2026-11-10": 10000})
    obs = _obs(26831 - 54, as_of="2026-11-12")

    facts = compute(day="2026-11-12", profile=profile, observation=obs, history=History(archive, day="2026-11-12"))

    assert facts.month.spent == 54
    assert facts.pace.today == 54


def test_fixed_transfer_is_saving_not_spending(tmp_path: Path) -> None:
    """每月固定转去理财账户的钱，是存起来，不该算成花销。"""
    raw = (
        "- 目标：100 万\n- 当前存款：20 万\n"
        "- 约定：目标日期 = 2030-12\n- 约定：月收入 = 16831\n"
        "- 约定：工资到账日 = 每月 11 号\n"
        "- 约定：固定转存 = 5000\n- 约定：固定转存日 = 每月 11 号\n"
    )
    profile = parse_profile(raw, tmp_path / "profile.md")
    archive = _archive(tmp_path / "archive", {"2026-11-10": 10000})
    obs = _obs(26831 - 5000 - 54, as_of="2026-11-12")

    facts = compute(day="2026-11-12", profile=profile, observation=obs, history=History(archive, day="2026-11-12"))

    assert facts.month.spent == 54
    assert facts.pace.today == 54
