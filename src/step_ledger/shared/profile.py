"""`materials/profile.md`：目标 / 存款 / 偏好的单一事实源。

解析刻意宽松：写成 `- 目标：100 万`、`目标: 1000000` 都认。
读不到就按默认目标（100 万）继续，不阻塞管线。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from math import ceil
from pathlib import Path

from .config import DEFAULT_TARGET

TEMPLATE = """# 理财档案

- 目标：100 万
- 当前存款：
- 提醒时间：21:00
- 偏好：说人话，别太严厉
- 约定：

> 这是 StepLedger 的长期状态，随时可以改。
"""

_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(亿|万|w|k|千)?", re.IGNORECASE)
_TIME_RE = re.compile(r"(\d{1,2})\s*[:：]\s*(\d{2})")
_LINE_RE = re.compile(r"^\s*[-*+]?\s*([\u4e00-\u9fa5A-Za-z ]{1,12})\s*[:：]\s*(.*)$")
_KV_RE = re.compile(r"^(?P<key>[^=＝]{1,20})[=＝]\s*(?P<value>.+)$")
_DEADLINE_RE = re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})")


@dataclass(frozen=True)
class GoalPlan:
    """目标日期的倒推：还剩几个月、每月要存多少（不计收益）。"""

    deadline: str
    months: int
    per_month: int


@dataclass
class Profile:
    path: Path
    exists: bool
    raw: str = ""
    target: int = DEFAULT_TARGET
    savings: int | None = None
    savings_from_materials: bool = False
    preferred_time: str | None = None
    created: bool = False
    agreements: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def distance(self) -> int | None:
        """离目标还差多少；不知道存款时返回 None（不猜）。"""
        if self.savings is None:
            return None
        return max(self.target - self.savings, 0)

    @property
    def percent(self) -> float | None:
        if self.savings is None or self.target <= 0:
            return None
        return min(max(self.savings / self.target, 0.0), 1.0)


def parse_amount(text: str | None) -> int | None:
    """把 `12.5 万` / `1,200` / `¥88` 解析成整数元。"""
    if not text:
        return None
    cleaned = text.replace(",", "").replace("，", "").replace("¥", "").replace("￥", "")
    match = _AMOUNT_RE.search(cleaned)
    if not match:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "").lower()
    scale = {"亿": 100_000_000, "万": 10_000, "w": 10_000, "k": 1_000, "千": 1_000}.get(unit, 1)
    return int(round(amount * scale))


def _parse_time(value: str | None) -> str | None:
    if not value:
        return None
    match = _TIME_RE.search(value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def load_profile(path: Path) -> Profile:
    if not path.is_file():
        return Profile(path=path, exists=False)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return Profile(path=path, exists=False)
    return parse_profile(raw, path)


def parse_profile(raw: str, path: Path) -> Profile:
    profile = Profile(path=path, exists=True, raw=raw)
    for line in raw.splitlines():
        match = _LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1).strip(), match.group(2).strip()
        if not value:
            continue
        if key == "约定":
            _remember_agreement(profile, value)
            continue
        if "目标" in key:
            parsed = parse_amount(value)
            if parsed:
                profile.target = parsed
        elif "存款" in key or "余额" in key:
            parsed = parse_amount(value)
            if parsed is not None:
                profile.savings = parsed
        elif "提醒" in key or "时间" in key:
            parsed_time = _parse_time(value)
            if parsed_time:
                profile.preferred_time = parsed_time
    return profile


def _remember_agreement(profile: Profile, text: str) -> None:
    """`键 = 值` 记成结构化约定（代码能用），其余原话进 prompt 给人读。"""
    match = _KV_RE.match(text.strip())
    if match:
        profile.agreements[match["key"].strip()] = match["value"].strip()
    else:
        profile.notes.append(text.strip())


def goal_plan(profile: Profile, today: str) -> GoalPlan | None:
    """读 `约定：目标日期 = 2030-12`，算出还剩几个月、每月要存多少（不计收益）。"""
    match = _DEADLINE_RE.search(profile.agreements.get("目标日期", ""))
    if not match or profile.distance is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    try:
        current = date.fromisoformat(today)
    except ValueError:
        return None
    months = (year - current.year) * 12 + (month - current.month)
    if months < 0:
        return None
    months = max(months, 1)
    return GoalPlan(deadline=f"{year}-{month:02d}", months=months, per_month=ceil(profile.distance / months))


def ensure_profile(path: Path) -> Profile:
    """缺文件就写一份模板，让人和 agent 都有东西可改。"""
    if path.is_file():
        return load_profile(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    profile = load_profile(path)
    profile.created = True
    return profile


def format_money(amount: int | None) -> str:
    return "未填写" if amount is None else f"¥{amount:,}"
