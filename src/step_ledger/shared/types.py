"""跨层共享的数据类型。层间只通过这里定义的结构对话。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .profile import Profile


@dataclass
class Judgment:
    """判断层的产物：一句有温度的花销总结 + 一条可执行的理财建议。"""

    summary: str
    advice: str
    prompt: str = ""
    degraded: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return bool(self.summary.strip()) and bool(self.advice.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "advice": self.advice,
            "prompt": self.prompt,
            "degraded": self.degraded,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Judgment":
        return cls(
            summary=str(data.get("summary", "")),
            advice=str(data.get("advice", "")),
            prompt=str(data.get("prompt", "")),
            degraded=bool(data.get("degraded", False)),
            meta=dict(data.get("meta") or {}),
        )


@dataclass
class CollectResult:
    """采集层的产物：当天素材目录，以及这次新增/跳过的文件。"""

    materials_dir: Path
    files: list[Path] = field(default_factory=list)
    added: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class RenderContext:
    """渲染层需要的上下文：日期、归档目录、档案快照。"""

    date: str
    archive_dir: Path
    profile: Profile
    material_count: int = 0
    profile_created: bool = False
    echo: bool = True


@dataclass
class RenderResult:
    """渲染层的产物：渠道名、给人看的输出、落盘文件。"""

    channel: str
    output: str = ""
    artifacts: list[Path] = field(default_factory=list)


@dataclass
class PipelineResult:
    """一次管线运行的全部结果，供 CLI / agent 转述。"""

    date: str
    materials_dir: Path
    archive_dir: Path
    judgment: Judgment | None = None
    renders: list[RenderResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    stage: str = "all"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "stage": self.stage,
            "materials_dir": str(self.materials_dir),
            "archive_dir": str(self.archive_dir),
            "skipped": self.skipped,
            "judgment": None if self.judgment is None else self.judgment.to_dict(),
            "renders": [
                {
                    "channel": r.channel,
                    "output": r.output,
                    "artifacts": [str(p) for p in r.artifacts],
                }
                for r in self.renders
            ],
        }


# ── 事实：判断层算，渲染层只读 ─────────────────────────────────────
#
# 「本月已花 / 今日额度 / 明天该多少」这类数由代码算，模型既不产也不改。
# 它们跨层（judge → render），所以和 Judgment 一样住在这里。


@dataclass(frozen=True)
class BalanceObs:
    """一条余额观测：模型从素材里读出的数，以及它读的那段原文（可回溯）。"""

    value: int | None = None
    as_of: str | None = None
    excerpt: str = ""
    confidence: str = "none"  # ok | suspect | none


@dataclass(frozen=True)
class Observation:
    """模型这一步唯一的产物。它不评价、不建议，只把余额读出来。"""

    balance: BalanceObs = field(default_factory=BalanceObs)
    anomalies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "balance": {
                "value": self.balance.value,
                "as_of": self.balance.as_of,
                "excerpt": self.balance.excerpt,
                "confidence": self.balance.confidence,
            },
            "anomalies": list(self.anomalies),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Observation":
        payload = data or {}
        raw = payload.get("balance")
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            balance=BalanceObs(
                value=_as_int(raw.get("value")),
                as_of=_as_str(raw.get("as_of")),
                excerpt=_as_str(raw.get("excerpt")) or "",
                confidence=_as_str(raw.get("confidence")) or "none",
            ),
            anomalies=tuple(str(item) for item in (payload.get("anomalies") or []) if str(item).strip()),
        )


@dataclass(frozen=True)
class GoalFacts:
    """离目标多远。savings 优先取档案手填值，没填才用当天余额兜底。"""

    target: int
    savings: int | None = None
    savings_source: str = "none"  # profile | balance | none
    distance: int | None = None
    percent: float | None = None
    deadline: str | None = None
    months: int | None = None
    per_month: int | None = None


@dataclass(frozen=True)
class MonthFacts:
    """本月：从哪天的余额起算、已花多少、还能花多少。"""

    key: str
    baseline_date: str | None = None
    baseline: int | None = None
    partial: bool = False
    spent: int | None = None
    spent_as_of: str | None = None
    income: int | None = None
    saving: int | None = None
    spendable: int | None = None
    left: int | None = None
    short: bool = False


@dataclass(frozen=True)
class PaceFacts:
    """把本月可花摊到每一天：今天额度、结余还是超支、明天该多少。"""

    days: int
    index: int
    quota: int
    allowed: int = 0
    today: int | None = None
    left: int = 0
    over: bool = False
    tomorrow: int | None = None


@dataclass(frozen=True)
class Facts:
    """当天的事实快照。判断层写一次，渲染层只读。"""

    date: str
    backfilled: bool = False
    balance: BalanceObs = field(default_factory=BalanceObs)
    goal: GoalFacts = field(default_factory=lambda: GoalFacts(target=0))
    month: MonthFacts | None = None
    pace: PaceFacts | None = None


@dataclass(frozen=True)
class DayPoint:
    """趋势图上的一天。quota / over 只在同一个月的日子里给。"""

    day: str
    spent: int | None = None
    quota: int | None = None
    over: bool = False


@dataclass(frozen=True)
class ProgressPoint:
    """进度历史的一天（milestones.md 用）。"""

    day: str
    savings: int | None = None
    percent: float | None = None


@dataclass(frozen=True)
class TrendSummary:
    """秘书翻的旧账：近两周每天花了多少、周环比、有没有持续超支。"""

    days: list[DayPoint] = field(default_factory=list)
    week_spent: int | None = None
    prev_week_spent: int | None = None
    over_days: int = 0
    balance_low: int | None = None
    progress: list[ProgressPoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "days": [asdict(point) for point in self.days],
            "week_spent": self.week_spent,
            "prev_week_spent": self.prev_week_spent,
            "over_days": self.over_days,
            "balance_low": self.balance_low,
            "progress": [asdict(point) for point in self.progress],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TrendSummary":
        payload = data or {}
        days = [
            DayPoint(
                day=_as_str(item.get("day")) or "",
                spent=_as_int(item.get("spent")),
                quota=_as_int(item.get("quota")),
                over=bool(item.get("over")),
            )
            for item in (payload.get("days") or [])
            if isinstance(item, dict)
        ]
        progress = [
            ProgressPoint(
                day=_as_str(item.get("day")) or "",
                savings=_as_int(item.get("savings")),
                percent=_as_float(item.get("percent")),
            )
            for item in (payload.get("progress") or [])
            if isinstance(item, dict)
        ]
        return cls(
            days=days,
            week_spent=_as_int(payload.get("week_spent")),
            prev_week_spent=_as_int(payload.get("prev_week_spent")),
            over_days=_as_int(payload.get("over_days")) or 0,
            balance_low=_as_int(payload.get("balance_low")),
            progress=progress,
        )


def facts_to_dict(facts: Facts) -> dict[str, Any]:
    return asdict(facts)


def facts_from_dict(data: dict[str, Any] | None) -> Facts | None:
    """从 judgment.json 里读回来；认不出就返回 None，不猜。"""
    payload = data or {}
    day = _as_str(payload.get("date"))
    if not day:
        return None
    raw_balance = payload.get("balance")
    raw_balance = raw_balance if isinstance(raw_balance, dict) else {}
    raw_goal = payload.get("goal")
    raw_goal = raw_goal if isinstance(raw_goal, dict) else {}
    return Facts(
        date=day,
        backfilled=bool(payload.get("backfilled")),
        balance=BalanceObs(
            value=_as_int(raw_balance.get("value")),
            as_of=_as_str(raw_balance.get("as_of")),
            excerpt=_as_str(raw_balance.get("excerpt")) or "",
            confidence=_as_str(raw_balance.get("confidence")) or "none",
        ),
        goal=GoalFacts(
            target=_as_int(raw_goal.get("target")) or 0,
            savings=_as_int(raw_goal.get("savings")),
            savings_source=_as_str(raw_goal.get("savings_source")) or "none",
            distance=_as_int(raw_goal.get("distance")),
            percent=_as_float(raw_goal.get("percent")),
            deadline=_as_str(raw_goal.get("deadline")),
            months=_as_int(raw_goal.get("months")),
            per_month=_as_int(raw_goal.get("per_month")),
        ),
        month=_month_from_dict(payload.get("month")),
        pace=_pace_from_dict(payload.get("pace")),
    )


def _month_from_dict(data: Any) -> MonthFacts | None:
    if not isinstance(data, dict):
        return None
    key = _as_str(data.get("key"))
    if not key:
        return None
    return MonthFacts(
        key=key,
        baseline_date=_as_str(data.get("baseline_date")),
        baseline=_as_int(data.get("baseline")),
        partial=bool(data.get("partial")),
        spent=_as_int(data.get("spent")),
        spent_as_of=_as_str(data.get("spent_as_of")),
        income=_as_int(data.get("income")),
        saving=_as_int(data.get("saving")),
        spendable=_as_int(data.get("spendable")),
        left=_as_int(data.get("left")),
        short=bool(data.get("short")),
    )


def _pace_from_dict(data: Any) -> PaceFacts | None:
    if not isinstance(data, dict):
        return None
    days = _as_int(data.get("days"))
    if not days:
        return None
    return PaceFacts(
        days=days,
        index=_as_int(data.get("index")) or 0,
        quota=_as_int(data.get("quota")) or 0,
        allowed=_as_int(data.get("allowed")) or 0,
        today=_as_int(data.get("today")),
        left=_as_int(data.get("left")) or 0,
        over=bool(data.get("over")),
        tomorrow=_as_int(data.get("tomorrow")),
    )


def _as_int(value: Any) -> int | None:
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


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
