"""DeepSeek Harness 桌宠渠道：生成 DSH Pet 提示词、离线/在线解读并归档 pet_status.json 与 pet.md。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..base import BaseChannel
from ...shared.profile import format_money
from ...shared.types import Judgment, RenderContext, RenderResult

DSH_PET_SYSTEM_PROMPT = """你是 DeepSeek Harness 桌宠（Aemeath），正在陪伴主人的每日理财复盘。
请根据主人的每日复盘总结、理财建议、存款进度和状态，以桌宠轻快、有温度、说人话且鼓励主人的口气进行回应。

你必须直接返回一个合法的 JSON 对象，格式如下：
{
  "mood": "happy|normal|worried|celebrating|thinking",
  "action": "jumping|running|thinking|failed|idle",
  "bubble_text": "简短的一两句气泡台词（30字以内）"
}
"""


def build_dsh_pet_prompt(judgment: Judgment, ctx: RenderContext) -> str:
    progress_pct = f"{ctx.profile.percent * 100:.1f}%" if ctx.profile.percent is not None else "未知"
    savings_str = format_money(ctx.profile.savings) if ctx.profile.savings is not None else "未填写"
    target_str = format_money(ctx.profile.target) if ctx.profile.target is not None else "未设置"

    lines = [
        f"日期: {ctx.date}",
        f"最近总结: {judgment.summary}",
        f"理财建议: {judgment.advice}",
        f"存款进度: {progress_pct} (当前存款: {savings_str} / 目标: {target_str})",
        f"降级模式: {'是' if judgment.degraded else '否'}",
    ]
    return "\n".join(lines)


def rule_based_pet_status(judgment: Judgment, ctx: RenderContext) -> dict[str, str]:
    """离线/降级/无 API 时使用的规则引擎，产生具有温度的桌宠状态与台词。"""
    summary = judgment.summary or ""
    advice = judgment.advice or ""

    if judgment.degraded:
        return {
            "mood": "thinking",
            "action": "thinking",
            "bubble_text": "今天虽然是降级模式，但我依然贴心为你记录好啦！",
        }

    if ctx.profile.percent is not None and ctx.profile.percent >= 1.0:
        return {
            "mood": "celebrating",
            "action": "jumping",
            "bubble_text": f"🎉 恭喜！存款已达 {format_money(ctx.profile.savings)}，实现100%小目标！",
        }

    income_keywords = ("收入", "工资", "到账", "奖金", "进账", "赚", "收益")
    if any(kw in summary for kw in income_keywords):
        return {
            "mood": "happy",
            "action": "jumping",
            "bubble_text": f"好耶！有新的收入进账，离目标又近一步啦✨",
        }

    overspend_keywords = ("大手大脚", "超支", "贵", "肉疼", "浪费", "花得挺多", "超预算")
    if any(kw in summary for kw in overspend_keywords):
        return {
            "mood": "worried",
            "action": "failed",
            "bubble_text": "呜…今天口袋瘦了一点点，明天我们省着点花哦～",
        }

    short_advice = advice[:26] if advice else "明天也要继续加油哦～"
    return {
        "mood": "normal",
        "action": "running",
        "bubble_text": f"小步慢跑中：{short_advice}",
    }


def _call_llm_api(prompt: str, api_key: str, model: str, base_url: str, timeout: float = 10.0) -> dict[str, Any] | None:
    if not api_key:
        return None

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": DSH_PET_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        content = data["choices"][0]["message"]["content"]
        res = json.loads(content)
        if isinstance(res, dict) and "mood" in res and "action" in res and "bubble_text" in res:
            return res
    except Exception:
        pass
    return None


class DshPetChannel(BaseChannel):
    name = "dsh-pet"

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini", base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def render(self, judgment: Judgment, ctx: RenderContext) -> RenderResult:
        ctx.archive_dir.mkdir(parents=True, exist_ok=True)
        prompt = build_dsh_pet_prompt(judgment, ctx)

        # 优先通过 API 调用生成宠物反应，API 不可用或失败时自动退回规则匹配
        api_result = _call_llm_api(prompt, self.api_key, self.model, self.base_url)
        pet_status_data = api_result or rule_based_pet_status(judgment, ctx)

        full_status = {
            "date": ctx.date,
            "pet_name": "Aemeath",
            "mood": pet_status_data.get("mood", "normal"),
            "action": pet_status_data.get("action", "idle"),
            "bubble_text": pet_status_data.get("bubble_text", "今天也要加油哦！"),
            "prompt": prompt,
            "summary": judgment.summary,
            "advice": judgment.advice,
            "progress": {
                "target": ctx.profile.target,
                "savings": ctx.profile.savings,
                "distance": ctx.profile.distance,
                "percent": ctx.profile.percent,
            },
            "degraded": judgment.degraded,
        }

        # 归档 pet_status.json
        json_path = ctx.archive_dir / "pet_status.json"
        json_path.write_text(json.dumps(full_status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # 归档 pet.md
        pet_md_content = self._format_pet_markdown(full_status)
        md_path = ctx.archive_dir / "pet.md"
        md_path.write_text(pet_md_content, encoding="utf-8")

        if ctx.echo:
            print(pet_md_content)

        return RenderResult(
            channel=self.name,
            output=pet_md_content,
            artifacts=[json_path, md_path],
        )

    def _format_pet_markdown(self, status: dict[str, Any]) -> str:
        lines = [
            f"# {status['date']} · DeepSeek Harness 桌宠 (Aemeath)",
            f"- 情绪: `{status['mood']}` | 动作: `{status['action']}`",
            "```text",
            "┌────────────────────────────────────────────────────────┐",
            f"│ 💬 宠物寄语: {status['bubble_text']:<41} │",
            "└────────────────────────────────────────────────────────┘",
            "```",
            f"最近总结：{status['summary']}",
            f"理财建议：{status['advice']}",
        ]
        return "\n".join(lines) + "\n"


__all__ = ["DshPetChannel", "build_dsh_pet_prompt", "rule_based_pet_status"]
