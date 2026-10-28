"""Stub 判断层：不调模型，用固定语气模板给出定性判断。

它同时是两条路径的兜底：没配 API key 时用它，真实 provider 挂掉也用它（并标注降级）。
"""

from __future__ import annotations

from pathlib import Path

from ..base import BaseProvider
from ..prompt import build_prompt, read_materials
from ...shared.profile import Profile, format_money
from ...shared.types import Judgment

_SPEND_HINTS = ("支出", "花了", "付款", "消费", "买", "打车", "外卖", "房租")
_INCOME_HINTS = ("收入", "工资", "到账", "退款", "报销", "奖金")


class StubProvider(BaseProvider):
    name = "stub"

    def judge(self, materials_dir: Path, profile: Profile, date: str = "") -> Judgment:
        text, skipped = read_materials(materials_dir)
        files = [p for p in materials_dir.iterdir() if p.is_file() and p.name != "profile.md"] if materials_dir.is_dir() else []
        prompt = build_prompt(profile, text, date, len(files))

        if not text.strip():
            summary = "今天没有记录，空白也是一种信息——至少没有意外的大额。"
            advice = "明天随手记一条就好，哪怕是「午饭 30」这种；有记录，判断才有依据。"
            meta = {"provider": self.name, "material_count": 0}
        else:
            spend = sum(text.count(hint) for hint in _SPEND_HINTS)
            income = sum(text.count(hint) for hint in _INCOME_HINTS)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            summary = self._summary(spend, income)
            advice = self._advice(spend, income, profile)
            meta = {
                "provider": self.name,
                "material_count": len(files),
                "line_count": len(lines),
                "spend_mentions": spend,
                "income_mentions": income,
            }

        if profile.distance is not None:
            meta["distance"] = profile.distance
        meta["skipped"] = skipped
        return Judgment(summary=summary, advice=advice, prompt=prompt, meta=meta)

    @staticmethod
    def _summary(spend: int, income: int) -> str:
        if spend == 0 and income == 0:
            return "今天的记录里没看到明显的进出账，日子过得比较平稳，这种平静其实挺值钱。"
        if income and spend:
            return f"今天有进有出，像是正常过日子的一天；花了 {spend} 笔、进了 {income} 笔，节奏不算失控。"
        if income:
            return "今天主要是进账，兜里松了一点；别忘了松的时候最容易顺手多花。"
        if spend == 1:
            return "今天只动了一次钱，克制得不错，这种感觉可以多留几天。"
        return f"今天花了 {spend} 笔，属于正常的日子；不用紧张，但值得看一眼最大那笔。"

    @staticmethod
    def _advice(spend: int, income: int, profile: Profile) -> str:
        if income and spend:
            base = "进账后先留一小份不动，剩下的再花，月底会轻松很多。"
        elif income:
            base = "趁手头松，把今天进账的一小部分单独放起来，别等它变成日常。"
        elif spend >= 4:
            base = "翻一眼今天最大的一笔，问问自己值不值；值就安心，犹豫的话明天先把它放一放。"
        else:
            base = "保持今天这种随手记一下的习惯，比记多细都重要。"
        if profile.distance is not None and profile.distance > 0:
            base += f"离 {format_money(profile.target)} 还有 {format_money(profile.distance)}，慢慢来就好。"
        return base


__all__ = ["StubProvider"]
