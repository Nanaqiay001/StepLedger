"""IM 渠道：把判断结果整理成一条能直接发出去的短消息。

**这个渠道不发送任何东西。** 原因在传输层：很多 IM 机器人（尤其是个人微信的智能机器人）
只能回应用户消息，不能主动推送；定时任务那一轮没有入站消息，发出去也到不了。

所以这里和 `pet` 同构：只产出 `archive/<日期>/im_task.md`，把「发什么」和「怎么发」
写清楚，由宿主 agent 在用户下一条消息时补发。补发完 `touch` 一个 `.sent` 标记，
避免同一条被重复发。

如果宿主接的是**能主动推送**的通道（企业微信机器人 / Telegram / 飞书 webhook 等），
那就不该用本渠道，而应该加一个直接 POST 的 webhook 渠道——两者的传输能力不同，
不要混在一起。
"""

from __future__ import annotations

from pathlib import Path

from ..base import BaseChannel
from ...shared.profile import format_money
from ...shared.types import Facts, Judgment, RenderContext, RenderResult

#: IM 里超过 4 行就没人看了；正文最多这么多条
MAX_LINES = 4


class IMChannel(BaseChannel):
    """产出待发消息。不联网、不主动推。"""

    name = "im"
    broadcast = True  # 清点历史时跳过：补账不是新闻

    def render(self, judgment: Judgment, ctx: RenderContext) -> RenderResult:
        ctx.out_dir.mkdir(parents=True, exist_ok=True)
        body = build_body(judgment)
        text = _render_task(judgment, body, ctx.out_dir)
        path = ctx.out_dir / "im_task.md"
        path.write_text(text, encoding="utf-8")
        if ctx.echo:
            print(f"IM 待发：{path}（用户下次说话时补发）")
        return RenderResult(channel=self.name, output=text, artifacts=[path])


def build_body(judgment: Judgment) -> list[str]:
    """正文：最多 4 行，说人话，不复述原始数据。"""
    lines: list[str] = []
    facts = judgment.facts
    if facts is not None:
        pace = facts.pace
        if pace is not None:
            if pace.over:
                tail = (
                    f"；明天降到 {format_money(pace.tomorrow)} 匀回来"
                    if pace.tomorrow is not None
                    else ""
                )
                lines.append(f"今天花了 {format_money(pace.today)}，超日额度 {format_money(-pace.left)}{tail}。")
            else:
                tail = f"；明天照 {format_money(pace.tomorrow)}" if pace.tomorrow is not None else ""
                lines.append(f"今天花了 {format_money(pace.today)}，还剩 {format_money(pace.left)} 额度{tail}。")
        month = facts.month
        if month is not None and month.left is not None:
            if month.short:
                lines.append(f"本月已经超了 {format_money(-month.left)}，这几天先贴着额度走。")
            else:
                lines.append(
                    f"本月还能花 {format_money(month.left)}"
                    f"（已花 {format_money(month.spent)} / 可花 {format_money(month.spendable)}）。"
                )
        trend = judgment.trend
        if trend.week_spent is not None:
            tail = f"，{trend.over_days} 天超额度" if trend.over_days else ""
            lines.append(f"近 7 天 {format_money(trend.week_spent)}{tail}。")
    if judgment.advice.strip():
        lines.append(judgment.advice.strip())
    return lines[:MAX_LINES] or ["今天没有记录，明天随手记一条就好。"]


def _render_task(judgment: Judgment, body: list[str], out_dir: Path) -> str:
    day = judgment.facts.date if judgment.facts is not None else ""
    chart = out_dir / "trend.svg"
    if chart.is_file():
        chart_lines = [
            f"- 图源：{chart}",
            "- IM 一般只收 PNG：先转一次，再发",
            f"  `sips -s format png '{chart}' --out '{out_dir / 'im.png'}'`",
        ]
    else:
        chart_lines = ["- 今天没有可画的余额点，只发文字"]
    return "\n".join(
        [
            f"# IM 待发 · {day}",
            "",
            "## 正文（原样发出去，别加长）",
            "",
            *body,
            "",
            "## 图",
            "",
            *chart_lines,
            "",
            "## 怎么发",
            "",
            "1. 用户下次说话时，把「正文」那几行作为回复发出去；",
            "2. 用 `dsh_im_return_file` 发 PNG（没有图就只发文字）；",
            f"3. 发完 `touch '{out_dir / 'im_task.md.sent'}'`，别重复发。",
            "",
            "> 为什么不是自动发：IM 机器人多半只能回复、不能主动推送；定时任务那一轮没有入站消息。",
            "> 这里是**待发**，不是已发。",
            "",
        ]
    )


__all__ = ["IMChannel", "MAX_LINES", "build_body"]
