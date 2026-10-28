"""判断层的公共部分：读素材、拼 prompt、解析模型返回。

两个 provider 共用同一份 prompt，保证 stub 与真实模型的口味一致。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..shared.profile import Profile, format_money

SYSTEM_PROMPT = """你是 StepLedger（跬步账）的判断器。用户每天把收支素材交给你，
你要说两件事：最近钱花得怎么样（summary）、下一步可以怎么调（advice）。

要求：
- 定性，不定量：不做精确对账、不列分类报表、不判定预算超支
- 有温度，说人话：像朋友提醒一句，不是财务审计
- 具体可感：能指出素材里真实出现的细节，不编造数字
- 建议是启发不是命令，不制造焦虑，不承诺收益
- 只输出 JSON：{"summary": "...", "advice": "..."}，两个字段都非空
"""

MAX_MATERIAL_CHARS = 8000
TEXT_SUFFIXES = {".md", ".txt", ".markdown", ".csv", ".log", ".json", ".yaml", ".yml"}


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


def build_prompt(profile: Profile, materials_text: str, date: str, material_count: int) -> str:
    savings = format_money(profile.savings)
    distance = "未知" if profile.distance is None else format_money(profile.distance)
    materials = materials_text.strip() or "（今天没有留下任何素材）"
    return f"""今天是 {date}。

## 我的档案
- 目标：{format_money(profile.target)}
- 当前存款：{savings}
- 离目标还差：{distance}
- 偏好：{_preference(profile)}

## 今天的素材（共 {material_count} 份）
{materials}

## 你要做的
用两三句话说说最近钱花得怎么样，再给一条明天就能动手的小调整。
参考目标，但别做审计、别算总账。只输出 JSON。
"""


def _preference(profile: Profile) -> str:
    for line in profile.raw.splitlines():
        if "偏好" in line:
            parts = re.split(r"[:：]", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return "说人话，别太严厉"


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
