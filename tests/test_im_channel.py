"""IM 渠道：只产待发消息，不联网、不主动推；清点时跳过。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from step_ledger.render.channels.im import IMChannel, MAX_LINES, build_body
from step_ledger.shared.types import (
    Facts,
    GoalFacts,
    Judgment,
    MonthFacts,
    PaceFacts,
    RenderContext,
    TrendSummary,
)


def _judgment(**overrides) -> Judgment:
    facts = Facts(
        date="2026-11-04",
        goal=GoalFacts(target=1_000_000, savings=200_000, savings_source="profile"),
        month=MonthFacts(
            key="2026-11",
            spent=432,
            spent_as_of="2026-11-04",
            spendable=3_081,
            left=2_649,
        ),
        pace=PaceFacts(days=30, index=4, quota=103, allowed=419, today=212, left=-21, over=True, tomorrow=102),
    )
    payload = dict(
        summary="s",
        advice="明天可以试试给小额支出设个「一次就好」的规矩。",
        facts=facts,
        trend=TrendSummary(week_spent=937, over_days=1),
    )
    payload.update(overrides)
    return Judgment(**payload)


def _ctx(tmp_path: Path) -> RenderContext:
    return RenderContext(out_dir=tmp_path / "archive" / "2026-11-04", echo=False)


def test_channel_is_broadcast_but_not_network() -> None:
    assert IMChannel.broadcast is True
    source = Path(IMChannel.__module__.replace(".", "/") + ".py")
    text = (Path(__file__).resolve().parents[1] / "src" / source).read_text(encoding="utf-8")
    assert "urllib" not in text  # 渠道自己不发送


def test_body_is_short_and_speaks_facts(tmp_path: Path) -> None:
    body = build_body(_judgment())

    assert len(body) <= MAX_LINES
    assert "今天花了 ¥212" in body[0]
    assert "超日额度 ¥21" in body[0]
    assert "明天降到 ¥102 匀回来" in body[0]
    assert "本月还能花 ¥2,649" in body[1]
    assert "近 7 天 ¥937" in body[2]
    assert "1 天超额度" in body[2]


def test_writes_task_with_delivery_recipe(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.out_dir.mkdir(parents=True)
    (ctx.out_dir / "trend.svg").write_text("<svg/>", encoding="utf-8")

    result = IMChannel().render(_judgment(), ctx)

    assert result.artifacts[0].name == "im_task.md"
    text = result.artifacts[0].read_text(encoding="utf-8")
    assert "待发" in text
    assert "trend.svg" in text
    assert "dsh_im_return_file" in text
    assert "im_task.md.sent" in text
    assert "不是已发" in text


def test_without_chart_says_text_only(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    text = IMChannel().render(_judgment(), ctx).output

    assert "只发文字" in text


def test_without_week_data_skips_that_line(tmp_path: Path) -> None:
    judgment = _judgment(trend=TrendSummary())

    body = build_body(judgment)

    assert all("近 7 天" not in line for line in body)


def test_without_facts_still_says_something(tmp_path: Path) -> None:
    judgment = Judgment(summary="s", advice="明天记一条。")

    body = build_body(judgment)

    assert body == ["明天记一条。"]


def test_month_over_is_stated(tmp_path: Path) -> None:
    facts = replace(_judgment().facts, month=replace(_judgment().facts.month, left=-120, short=True))

    body = build_body(_judgment(facts=facts))

    assert "本月已经超了 ¥120" in body[1]


def test_pipeline_writes_im_task(cfg) -> None:
    from conftest import DATE
    from step_ledger.pipeline import run
    from step_ledger.shared.config import Config

    cfg = Config(**{**cfg.__dict__, "channels": ("console", "im")})

    run(date=DATE, payload="午饭 30", config=cfg, echo=False)

    assert (cfg.archive_for(DATE) / "im_task.md").is_file()


def test_settlement_does_not_prepare_im(cfg, monkeypatch) -> None:
    """清点是修正记录：不能给昨天再造一条待发消息。"""
    import json
    from datetime import date, timedelta

    from step_ledger.collect.adapters.manual import fingerprint
    from step_ledger.pipeline import settle
    from step_ledger.shared.config import Config
    from step_ledger.shared.types import BalanceObs, Facts, GoalFacts

    day = (date.today() - timedelta(days=1)).isoformat()
    materials = cfg.materials_for(day)
    materials.mkdir(parents=True)
    (materials / "sms.txt").write_text("旧内容", encoding="utf-8")
    digest = fingerprint(materials)
    archive = cfg.archive_for(day)
    archive.mkdir(parents=True)
    judgment = {
        "summary": "当初写的",
        "advice": "当初的建议",
        "facts": {"date": day, "balance": {"value": 12000, "as_of": day, "confidence": "ok"},
                  "goal": {"target": 1000000}},
        "runtime": {"materials_digest": digest},
    }
    (archive / "judgment.json").write_text(json.dumps(judgment, ensure_ascii=False), encoding="utf-8")
    with (materials / "sms.txt").open("a", encoding="utf-8") as handle:
        handle.write("\n晚一点")

    import step_ledger.pipeline as pipeline

    class Fake:
        name = "fake"

        def observe(self, materials_text, date=""):
            from step_ledger.shared.types import Observation

            return Observation(balance=BalanceObs(value=11800, as_of=date, excerpt="余额", confidence="ok"))

        def speak(self, materials_dir, profile, date="", facts=None, trend=None):
            return Judgment(summary="新", advice="新", prompt="p")

    monkeypatch.setattr(pipeline, "_build_provider", lambda cfg, name: Fake())

    cfg = Config(**{**cfg.__dict__, "channels": ("console", "im")})
    settle(cfg=cfg, day=day)

    assert (archive / "report.md").is_file()
    assert not (archive / "im_task.md").exists()
