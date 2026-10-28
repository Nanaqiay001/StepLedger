"""判断层：stub 的口味、响应解析、provider 的失败模式。"""

from __future__ import annotations

from pathlib import Path

import pytest

from step_ledger.collect.adapters.manual import collect
from step_ledger.judge.base import ProviderError
from step_ledger.judge.prompt import parse_judgment_response, read_materials
from step_ledger.judge.providers.openai_compatible import OpenAICompatibleProvider
from step_ledger.judge.providers.stub import StubProvider
from step_ledger.shared.profile import parse_profile


def _profile(tmp_path: Path):
    return parse_profile("- 目标：100 万\n- 当前存款：20 万\n", tmp_path / "profile.md")


def test_stub_with_materials_feels_personal(tmp_path: Path, normal_day: Path) -> None:
    materials = tmp_path / "2026-10-28"
    collect(materials, normal_day / "bill.md")

    judgment = StubProvider().judge(materials, _profile(tmp_path), "2026-10-28")

    assert judgment.is_valid
    assert judgment.degraded is False
    assert "¥800,000" in judgment.advice  # 离目标的距离
    assert judgment.prompt.strip()


def test_stub_without_materials_is_honest(tmp_path: Path) -> None:
    materials = tmp_path / "2026-10-28"
    materials.mkdir()

    judgment = StubProvider().judge(materials, _profile(tmp_path), "2026-10-28")

    assert "今天没有记录" in judgment.summary
    assert judgment.advice.strip()
    assert judgment.meta["material_count"] == 0


def test_parse_json_response() -> None:
    summary, advice, balance = parse_judgment_response('{"summary": "还好", "advice": "少点一次外卖"}')
    assert summary == "还好"
    assert advice == "少点一次外卖"
    assert balance is None


def test_parse_fenced_json_response() -> None:
    raw = '```json\n{"summary": "正常", "advice": "继续"}\n```'
    assert parse_judgment_response(raw) == ("正常", "继续", None)


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
