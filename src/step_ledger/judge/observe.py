"""观察：让模型从素材里读出一条余额，只读数，不评价。

模型给的是「观测」，不是「结论」。它的可信度由代码核验，而不是由它自己保证：

1. `excerpt` 必须能在当天素材原文里找到（归一化后子串）
2. `value` 必须能从 `excerpt` 的数字里读出来

两条都过 → `ok`；任一条不过 → `suspect`。这是确定性检查，没有格式假设，
也不需要任何正则去匹配某家银行的短信模板。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import replace
from datetime import date as date_type

from ..shared.types import BalanceObs, Observation

OBSERVE_SYSTEM_PROMPT = """你是 StepLedger 的观察器。你只做一件事：从素材里读出最新的账户余额，
不评价花销、不建议、不总结。

要求：
- value：只取原文写明的数；素材里没有就返回 null。不要估算、不要相加、不要从别的数字推。
- as_of：这条余额对应的日期（看原文的时间戳），格式 YYYY-MM-DD；读不到返回 null。
- excerpt：你读到 value 的那一段原文，**逐字复制**：不要改写标点、不要补全、不要跨条拼接。
- anomalies：值得记一笔的异常（有多个账户、重复推送、余额缺失等），没有就给 []。
- 只输出 JSON：{"balance": {"value": 数字或 null, "as_of": "YYYY-MM-DD", "excerpt": "..."}, "anomalies": []}
"""

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_observe_prompt(materials_text: str, date: str) -> str:
    materials = materials_text.strip() or "（今天没有留下任何素材）"
    return f"""今天是 {date}。

## 今天的素材
{materials}

## 你要做的
只读出素材里最新的账户余额，连同你读到它的那段原文。
不要评价花销、不要给建议、不要做统计。只输出 JSON。
"""


def parse_observation_response(text: str) -> Observation:
    """尽量从模型输出里抽出观测；连结构都不对就抛 ValueError。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("模型返回为空")
    candidate = raw
    fenced = _JSON_FENCE_RE.search(raw)
    if fenced:
        candidate = fenced.group(1)
    else:
        brace = _JSON_OBJECT_RE.search(raw)
        if brace:
            candidate = brace.group(0)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError("模型返回不是约定的 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("模型返回不是约定的 JSON")
    if "balance" not in data and not data.get("anomalies"):
        raise ValueError("模型返回缺 balance")
    return Observation.from_dict(data)


def verify(observation: Observation, materials_text: str, date: str = "") -> Observation:
    """用「原文可寻址」核验观测。核验只标 `suspect`，不改数值。"""
    balance = observation.balance
    anomalies = list(observation.anomalies)
    if balance.value is None:
        return Observation(
            balance=BalanceObs(value=None, as_of=None, excerpt=balance.excerpt, confidence="none"),
            anomalies=tuple(anomalies),
        )

    confidence = "ok"
    excerpt = (balance.excerpt or "").strip()
    if not excerpt:
        confidence = "suspect"
        anomalies.append("没有给出原文摘录")
    else:
        if normalize(excerpt) not in normalize(materials_text):
            confidence = "suspect"
            anomalies.append("摘录在当天素材里找不到")
        if not _has_amount(excerpt, balance.value):
            confidence = "suspect"
            anomalies.append("余额与摘录里的数字对不上")

    as_of = balance.as_of
    if not _is_date(as_of):
        as_of = date if _is_date(date) else None
        anomalies.append("没读到余额日期，按当天处理")
    elif _is_date(date) and as_of > date:
        confidence = "suspect"
        anomalies.append(f"余额日期 {as_of} 晚于当天 {date}")
        as_of = date

    return Observation(
        balance=BalanceObs(
            value=balance.value,
            as_of=as_of,
            excerpt=excerpt,
            confidence=confidence,
        ),
        anomalies=tuple(anomalies),
    )


def normalize(text: str) -> str:
    """全半角统一 + 去掉所有空白，避免模型改写标点就让核验失效。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def _has_amount(excerpt: str, value: int) -> bool:
    for token in _NUMBER_RE.findall(excerpt):
        try:
            number = float(token.replace(",", ""))
        except ValueError:
            continue
        if int(round(number)) == value or int(number) == value:
            return True
    return False


def _is_date(value: str | None) -> bool:
    if not value or len(value) != 10:
        return False
    try:
        date_type.fromisoformat(value)
    except ValueError:
        return False
    return True


__all__ = [
    "OBSERVE_SYSTEM_PROMPT",
    "build_observe_prompt",
    "normalize",
    "parse_observation_response",
    "verify",
]
