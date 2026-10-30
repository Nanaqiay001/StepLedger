"""DeepSeek Harness 桌宠渠道：组装复盘提示词并归档 dsh_prompt.md，可选地通过 dsh-ai-bridge 投递至常驻 DSH 会话。

恪守渲染层职责：渲染层只负责“呈现”，不做任何 AI 推理，不调用任何 LLM API。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

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
        "然后调用 pet_say 工具，让桌宠说出这句话（参数：{ text, mood? }，建议 mood：happy、worried 或 neutral；若当前环境或工具不支持所给 mood 参数则可忽略）。",
    ]
    return "\n".join(lines) + "\n"


def post_to_dsh_bridge(
    prompt_text: str, bridge_url: str = "", bridge_token: str = "", timeout: float = 10.0
) -> tuple[bool, str]:
    """通过 HTTP POST 将提示词投递到常驻 DSH 会话的 ai-bridge 端点。"""
    token = (bridge_token or "").strip()
    if not token:
        return False, "未配置 DSH_BRIDGE_TOKEN，跳过 DSH 投递"

    url = (bridge_url or "http://127.0.0.1:8000/api/ai-bridge/post").strip()
    payload = json.dumps({"from": "step-ledger", "text": prompt_text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-bridge-token": token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            if 200 <= status_code < 300:
                return True, f"提示词已成功通过 dsh-ai-bridge 投递至 DSH 会话 ({url})"
            return False, f"投递 DSH 失败 (HTTP {status_code}, 端点: {url})"
    except urllib.error.HTTPError as exc:
        return False, f"投递 DSH 失败 (HTTP {exc.code}, 端点: {url}): {exc.reason}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"投递 DSH 失败 ({type(exc).__name__}, 端点: {url}): {exc}"


class DshPetChannel(BaseChannel):
    """dsh-pet 提示词产出与投递渠道。

    本渠道将复盘结果组装为提示词归档到 dsh_prompt.md，并可选地通过 dsh-ai-bridge 投递至常驻 DSH 会话。
    前置假设：用户已常驻运行 DSH 会话并启用了桌宠插件。未配置令牌时退化为仅产出提示词文件。
    """

    name = "dsh-pet"

    def __init__(self, bridge_url: str = "", bridge_token: str = "") -> None:
        self.bridge_url = bridge_url
        self.bridge_token = bridge_token

    def render(self, judgment: Judgment, ctx: RenderContext) -> RenderResult:
        ctx.archive_dir.mkdir(parents=True, exist_ok=True)

        prompt_content = build_dsh_prompt(judgment, ctx)
        dsh_prompt_path = ctx.archive_dir / "dsh_prompt.md"
        dsh_prompt_path.write_text(prompt_content, encoding="utf-8")

        pet_md_content = self._format_pet_markdown(judgment, ctx)
        pet_md_path = ctx.archive_dir / "pet.md"
        pet_md_path.write_text(pet_md_content, encoding="utf-8")

        # 尝试通过 HTTP POST 投递到常驻 DSH 会话；失败时不崩溃
        success, detail = post_to_dsh_bridge(
            prompt_content,
            bridge_url=self.bridge_url,
            bridge_token=self.bridge_token,
        )

        output_msg = (
            f"# {ctx.date} · StepLedger dsh-pet 渠道\n"
            f"提示词归档：{dsh_prompt_path}\n"
            f"DSH 投递状态：{detail}\n"
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


__all__ = ["DshPetChannel", "build_dsh_prompt", "post_to_dsh_bridge"]
