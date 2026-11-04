"""判断层的公共部分：读素材、拼 prompt、解析模型返回。

两个 provider 共用同一份 prompt，保证 stub 与真实模型的口味一致。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..shared.profile import Profile, format_money, goal_plan
from ..shared.types import Facts, TrendSummary

SYSTEM_PROMPT = """你是 StepLedger（跬步账）的判断器。用户每天把收支素材交给你，
你要说两件事：最近钱花得怎么样（summary）、下一步可以怎么调（advice）。

要求：
- 定性，不定量：不做精确对账、不列分类报表，也不自己算预算
- 有温度，说人话：像朋友提醒一句，不是财务审计
- 具体可感：能指出素材里真实出现的细节
- 建议是启发不是命令，不制造焦虑，不承诺收益
- 只输出 JSON：{"summary": "...", "advice": "..."}

关于数字：
- 「已经算好的事实」是权威，直接引用，不要重新计算、不要自己加总
- 没有给出的数字不要编；读不出来就说不知道
"""

MAX_MATERIAL_CHARS = 8000
TEXT_SUFFIXES = {".md", ".txt", ".markdown", ".csv", ".log", ".json", ".yaml", ".yml"}
# 一次性口令不该离开本机：素材原样留在盘上，但发给模型前把这些行摘掉
SECRET_LINE = re.compile(r"验证码|校验码|动态密码|动态码|短信密码|安全码|切勿.{0,6}告知")


def strip_secrets(text: str) -> str:
    """摘掉验证码之类的一次性口令行：它们对判断没用，但泄露一次就是一次。"""
    kept = [line for line in text.splitlines() if not SECRET_LINE.search(line)]
    return "\n".join(kept)


def read_materials(materials_dir: Path, max_chars: int = MAX_MATERIAL_CHARS) -> tuple[str, list[str]]:
    """读当天素材，返回（拼好的文本, 跳过的文件说明）。读不了的就跳过，不阻塞。"""
    if not materials_dir.is_dir():
        return "", []
    chunks: list[str] = []
    skipped: list[str] = []
    total = 0
    for path in sorted(materials_dir.iterdir()):
        if not path.is_file() or path.name == "profile.md":
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            skipped.append(f"{path.name}: 非文本素材，暂不解析")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skipped.append(f"{path.name}: 无法解码，已跳过")
            continue
        text = strip_secrets(text)
        if not text.strip():
            continue
        piece = f"### {path.name}\n{text.strip()}"
        if total + len(piece) > max_chars:
            remaining = max_chars - total
            if remaining > 0:
                chunks.append(piece[:remaining] + "\n\n…（素材太长，已截断）")
            skipped.append(f"{path.name}: 超出单次上下文上限，已截断")
            break
        chunks.append(piece)
        total += len(piece)
    return "\n\n".join(chunks), skipped


def build_prompt(
    profile: Profile,
    materials_text: str,
    date: str,
    material_count: int,
    facts: Facts | None = None,
    trend: TrendSummary | None = None,
) -> str:
    savings = format_money(profile.savings)
    distance = "未知" if profile.distance is None else format_money(profile.distance)
    materials = materials_text.strip() or "（今天没有留下任何素材）"
    agreements = _agreements(profile)
    agreed = f"\n## 我的约定（按我的口径解读，别自己推断）\n{agreements}\n" if agreements else ""
    plan = goal_plan(profile, date)
    paced = (
        f"- 目标日期：{plan.deadline}（还剩 {plan.months} 个月，"
        f"每月要存 {format_money(plan.per_month)}，不计收益）\n"
        if plan
        else ""
    )
    computed = _facts_section(facts, trend)
    return f"""今天是 {date}。

## 我的档案
- 目标：{format_money(profile.target)}
- 当前存款：{savings}
- 离目标还差：{distance}
{paced}- 偏好：{_preference(profile)}
{agreed}
{computed}
## 今天的素材（共 {material_count} 份）
{materials}

## 你要做的
用两三句话说说最近钱花得怎么样，再给一条明天就能动手的小调整。
数字只能用上面给出的，别自己算、别做审计。只输出 JSON。
"""


def _agreements(profile: Profile) -> str:
    """档案里的「约定」逐条进 prompt：用户自己的口径优先于模型推断。"""
    items = [f"- {key}：{value}" for key, value in profile.agreements.items()]
    items += [f"- {note}" for note in profile.notes]
    return "\n".join(items)


def _preference(profile: Profile) -> str:
    for line in profile.raw.splitlines():
        if "偏好" in line:
            parts = re.split(r"[:：]", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return "说人话，别太严厉"


def _facts_section(facts: Facts | None, trend: TrendSummary | None) -> str:
    """把已经算好的事实写进 prompt：模型只引用，不重算。"""
    if facts is None:
        return ""
    lines: list[str] = ["## 已经算好的事实（权威，不可改，也不许自己重算）"]
    goal = facts.goal
    if goal.distance is not None:
        tail = (
            f"，剩 {goal.months} 个月，每月要存 {format_money(goal.per_month)}"
            if goal.months is not None and goal.per_month is not None
            else ""
        )
        lines.append(f"- 目标 {format_money(goal.target)}，还差 {format_money(goal.distance)}{tail}")
    month = facts.month
    if month is not None:
        if month.spendable is not None and month.spent is not None:
            tail = f"，还能花 {format_money(month.left)}" if month.left is not None else ""
            lines.append(
                f"- 本月可花 {format_money(month.spendable)}，已花 {format_money(month.spent)}{tail}"
            )
        elif month.spent is not None:
            note = f"（截至 {month.spent_as_of}）" if month.spent_as_of and month.spent_as_of != facts.date else ""
            lines.append(f"- 本月已花 {format_money(month.spent)}{note}")
    pace = facts.pace
    if pace is not None:
        parts = [f"- 今天额度 {format_money(pace.quota)}"]
        parts.append(
            "今天还没读到花费" if pace.today is None else f"今天花了 {format_money(pace.today)}"
        )
        if pace.over:
            parts.append(f"累计超了 {format_money(-pace.left)}")
        else:
            parts.append(f"累计结余 {format_money(pace.left)}")
        if pace.tomorrow is not None:
            parts.append(f"明天额度 {format_money(pace.tomorrow)}")
        lines.append("，".join(parts))
    if trend is not None and trend.week_spent is not None:
        line = f"- 近 7 天花了 {format_money(trend.week_spent)}"
        if trend.prev_week_spent is not None:
            change = trend.week_spent - trend.prev_week_spent
            word = "多" if change >= 0 else "少"
            line += f"，比前 7 天{word} {format_money(abs(change))}"
        if trend.over_days:
            line += f"，有 {trend.over_days} 天超了日额度"
        lines.append(line)
    if len(lines) == 1:
        return ""
    return "\n".join(lines) + "\n"


def parse_judgment_response(text: str) -> tuple[str, str]:
    """尽量从模型输出里抽出 summary / advice；抽不出就抛 ValueError。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("模型返回为空")
    candidate = raw
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        brace = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace:
            candidate = brace.group(0)
    try:
        data = json.loads(candidate)
        summary = str(data.get("summary", "")).strip()
        advice = str(data.get("advice", "")).strip()
        if summary and advice:
            return summary, advice
    except json.JSONDecodeError:
        pass
    raise ValueError("模型返回不是约定的 JSON")
