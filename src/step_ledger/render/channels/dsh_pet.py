"""DeepSeek Harness 桌宠渠道：将 Judgment 组装为给 dsh / Agent 消费的提示词，并归档 dsh_prompt.md 与 pet.md。

恪守渲染层职责：渲染层只负责“呈现”，不做任何 AI 推理，不调用任何 LLM API。
"""

from __future__ import annotations

from ..base import BaseChannel
from ...shared.profile import format_money
from ...shared.types import Judgment, RenderContext, RenderResult


def build_dsh_prompt(judgment: Judgment, ctx: RenderContext) -> str:
    """生成面向 DeepSeek Harness / Agent 的结构化提示词。"""
    progress_pct = f"{ctx.profile.percent * 100:.1f}%" if ctx.profile.percent is not None else "未知"
    savings_str = format_money(ctx.profile.savings) if ctx.profile.savings is not None else "未填写"
    target_str = format_money(ctx.profile.target) if ctx.profile.target is not None else "未设置"

    lines = [
        "【StepLedger 每日复盘】",
        f"日期：{ctx.date}",
        f"总结：{judgment.summary}",
        f"建议：{judgment.advice}",
        f"进度：{progress_pct} (当前存款: {savings_str} / 目标: {target_str})",
        "",
        "请根据以上内容，用一句话向用户播报今日复盘要点，语气轻松口语化。",
        "然后调用 pet_say 工具，让桌宠说出这句话（参数：{ text, mood? }）；mood 可根据进度或复盘结论选择 happy、worried 或 neutral。",
    ]
    return "\n".join(lines) + "\n"


class DshPetChannel(BaseChannel):
    """dsh-pet 提示词产出渠道。

    本渠道只产出给 dsh / Agent 消费的提示词文件（dsh_prompt.md），不调用 LLM API，不直接驱动桌宠。
    """

    name = "dsh-pet"

    def render(self, judgment: Judgment, ctx: RenderContext) -> RenderResult:
        ctx.archive_dir.mkdir(parents=True, exist_ok=True)

        prompt_content = build_dsh_prompt(judgment, ctx)
        dsh_prompt_path = ctx.archive_dir / "dsh_prompt.md"
        dsh_prompt_path.write_text(prompt_content, encoding="utf-8")

        pet_md_content = self._format_pet_markdown(judgment, ctx)
        pet_md_path = ctx.archive_dir / "pet.md"
        pet_md_path.write_text(pet_md_content, encoding="utf-8")

        output_msg = (
            f"# {ctx.date} · StepLedger dsh-pet 提示词渠道\n"
            f"提示词已产出：{dsh_prompt_path}（等待 dsh / Agent 消费）\n"
        )

        if ctx.echo:
            print(output_msg)

        return RenderResult(
            channel=self.name,
            output=output_msg,
            artifacts=[dsh_prompt_path, pet_md_path],
        )

    def _format_pet_markdown(self, judgment: Judgment, ctx: RenderContext) -> str:
        progress_pct = f"{ctx.profile.percent * 100:.1f}%" if ctx.profile.percent is not None else "未填写"
        lines = [
            f"# {ctx.date} · 跬步账复盘摘要 (dsh-pet)",
            f"- 存钱进度：{progress_pct}",
            f"- 最近总结：{judgment.summary}",
            f"- 理财建议：{judgment.advice}",
        ]
        return "\n".join(lines) + "\n"


__all__ = ["DshPetChannel", "build_dsh_prompt"]
