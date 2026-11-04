"""判断层：stub 的口味、响应解析、provider 的失败模式。"""

from __future__ import annotations

from pathlib import Path

import pytest

from step_ledger.collect.adapters.manual import collect
from step_ledger.judge.base import ProviderError
from step_ledger.judge.prompt import (
    build_prompt,
    parse_judgment_response,
    read_materials,
    strip_secrets,
)
from step_ledger.judge.providers.openai_compatible import OpenAICompatibleProvider
from step_ledger.judge.providers.stub import StubProvider
from step_ledger.shared.profile import parse_profile


def _profile(tmp_path: Path):
    return parse_profile("- 目标：100 万\n- 当前存款：20 万\n", tmp_path / "profile.md")


def test_stub_with_materials_feels_personal(tmp_path: Path, normal_day: Path) -> None:
    materials = tmp_path / "2026-10-28"
    collect(materials, normal_day / "bill.md")

    judgment = StubProvider().speak(materials, _profile(tmp_path), "2026-10-28")

    assert judgment.is_valid
    assert judgment.degraded is False
    assert "¥800,000" in judgment.advice  # 离目标的距离
    assert judgment.prompt.strip()


def test_stub_without_materials_is_honest(tmp_path: Path) -> None:
    materials = tmp_path / "2026-10-28"
    materials.mkdir()

    judgment = StubProvider().speak(materials, _profile(tmp_path), "2026-10-28")

    assert "今天没有记录" in judgment.summary
    assert judgment.advice.strip()
    assert judgment.runtime["material_count"] == 0


def test_prompt_carries_user_agreements(tmp_path: Path) -> None:
    """档案里的「约定」必须进 prompt：用户的口径优先于模型推断。"""
    raw = "- 目标：100 万\n- 约定：某笔固定小额是自动存钱，算存钱不算花销\n"
    profile = parse_profile(raw, tmp_path / "profile.md")

    prompt = build_prompt(profile, "一笔小额", "2026-10-31", 1)

    assert "## 我的约定" in prompt
    assert "某笔固定小额是自动存钱" in prompt


def test_prompt_without_agreements_has_no_empty_section(tmp_path: Path) -> None:
    profile = parse_profile("- 目标：100 万\n", tmp_path / "profile.md")

    prompt = build_prompt(profile, "午饭 35", "2026-10-31", 1)

    assert "我的约定" not in prompt
    assert "偏好：说人话" in prompt


def test_parse_json_response() -> None:
    summary, advice = parse_judgment_response('{"summary": "还好", "advice": "少点一次外卖"}')
    assert summary == "还好"
    assert advice == "少点一次外卖"


def test_parse_fenced_json_response() -> None:
    raw = '```json\n{"summary": "正常", "advice": "继续"}\n```'
    assert parse_judgment_response(raw) == ("正常", "继续")


def test_parse_rejects_non_json() -> None:
    with pytest.raises(ValueError):
        parse_judgment_response("今天挺好的")


def test_openai_provider_requires_key() -> None:
    with pytest.raises(ProviderError):
        OpenAICompatibleProvider(api_key="", model="gpt-4o-mini", base_url="https://example.com/v1")


def test_long_material_is_truncated(tmp_path: Path) -> None:
    materials = tmp_path / "2026-10-28"
    materials.mkdir()
    (materials / "big.md").write_text("买" * 500, encoding="utf-8")

    text, skipped = read_materials(materials, max_chars=100)

    assert "已截断" in text
    assert any("截断" in item for item in skipped)


def test_prompt_carries_goal_deadline(tmp_path: Path) -> None:
    """目标日期要进 prompt，让判断按节奏说话（还剩几个月、每月存多少）。"""
    profile = parse_profile(
        "- 目标：100 万\n- 当前存款：20 万\n- 约定：目标日期 = 2030-12\n", tmp_path / "profile.md"
    )

    prompt = build_prompt(profile, "午饭 35", "2026-11-02", 1)

    assert "目标日期：2030-12" in prompt
    assert "还剩 49 个月" in prompt
    assert "每月要存 ¥16,327" in prompt


def test_strip_secrets_drops_one_time_codes() -> None:
    """验证码对判断没用，泄露一次就是一次：发出去之前摘掉，素材原样留盘。"""
    text = (
        "{12:15}-{支取人民币 25.00 元,交易后余额 12292.98}\n"
        "{18:58}-{短信验证码：100442，切勿将验证码告知他人}\n"
        "{18:59}-{与财付通成功签约}\n"
    )

    kept = strip_secrets(text)

    assert "100442" not in kept
    assert "12292.98" in kept
    assert "成功签约" in kept


def test_read_materials_filters_secrets_but_keeps_file(tmp_path: Path) -> None:
    materials = tmp_path / "2026-11-02"
    materials.mkdir()
    source = materials / "sms.txt"
    source.write_text("验证码：999888，请勿告知\n支出 25.00 元\n", encoding="utf-8")

    text, _ = read_materials(materials)

    assert "999888" not in text
    assert "25.00" in text
    assert "999888" in source.read_text(encoding="utf-8")  # 盘上还是原样


def _facts() -> object:
    from step_ledger.shared.types import Facts, GoalFacts, MonthFacts, PaceFacts

    return Facts(
        date="2026-11-04",
        goal=GoalFacts(
            target=1_000_000,
            savings=200_000,
            savings_source="profile",
            distance=800_000,
            percent=0.2,
            deadline="2030-12",
            months=49,
            per_month=16_327,
        ),
        month=MonthFacts(
            key="2026-11",
            baseline_date="2026-10-31",
            baseline=12000,
            spent=600,
            spent_as_of="2026-11-04",
            income=16000,
            saving=12859,
            spendable=3141,
            left=2541,
        ),
        pace=PaceFacts(days=30, index=4, quota=105, allowed=419, today=100, left=-181, over=True, tomorrow=102),
    )


def test_prompt_carries_computed_facts(tmp_path: Path) -> None:
    """数字必须先进 prompt，模型才可能说出「明天匀回来」。"""
    profile = parse_profile("- 目标：100 万\n- 当前存款：20 万\n", tmp_path / "profile.md")

    prompt = build_prompt(profile, "咖啡 20", "2026-11-04", 1, _facts())

    assert "## 已经算好的事实" in prompt
    assert "本月可花 ¥3,141" in prompt
    assert "已花 ¥600" in prompt
    assert "明天额度 ¥102" in prompt
    assert "不许自己重算" in prompt


def test_prompt_without_facts_is_unchanged(tmp_path: Path) -> None:
    profile = parse_profile("- 目标：100 万\n", tmp_path / "profile.md")

    prompt = build_prompt(profile, "午饭 35", "2026-10-31", 1)

    assert "已经算好的事实" not in prompt


def test_prompt_carries_weekly_trend(tmp_path: Path) -> None:
    from step_ledger.shared.types import TrendSummary

    profile = parse_profile("- 目标：100 万\n", tmp_path / "profile.md")
    trend = TrendSummary(week_spent=1850, prev_week_spent=1530, over_days=2)

    prompt = build_prompt(profile, "咖啡 20", "2026-11-04", 1, _facts(), trend)

    assert "近 7 天花了 ¥1,850" in prompt
    assert "比前 7 天多 ¥320" in prompt
    assert "2 天超了日额度" in prompt


def test_stub_speaks_with_facts(tmp_path: Path, normal_day: Path) -> None:
    """降级路径也要说得出额度：模板直接用算好的数。"""
    materials = tmp_path / "2026-11-04"
    collect(materials, normal_day / "bill.md")
    profile = parse_profile("- 目标：100 万\n- 当前存款：20 万\n", tmp_path / "profile.md")

    judgment = StubProvider().speak(materials, profile, "2026-11-04", _facts())

    assert judgment.is_valid
    assert "匀回来" in judgment.advice
    assert "明天降到 ¥102" in judgment.advice


def test_parse_ignores_legacy_balance_field() -> None:
    """模型还按旧约定多给一个 balance，也不该解析失败。"""
    raw = '{"summary": "还好", "advice": "少点一次外卖", "balance": 12800}'

    assert parse_judgment_response(raw) == ("还好", "少点一次外卖")
