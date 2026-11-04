"""观察层：模型只读余额，代码负责核验「它读的数在原文里找得到」。"""

from __future__ import annotations

import pytest

from step_ledger.judge.observe import (
    build_observe_prompt,
    normalize,
    parse_observation_response,
    verify,
)
from step_ledger.judge.providers.openai_compatible import OpenAICompatibleProvider
from step_ledger.judge.providers.stub import StubProvider
from step_ledger.shared.types import BalanceObs, Observation

DAY = "2026-11-04"
SMS = (
    "{2026-11-04T12:15:03+08:00}-{您的借记卡账户1234，于11月04日网上支付支取人民币9.53元,"
    "交易后余额12800.00【中国银行】}"
)
RAW = (
    '{"balance": {"value": 12800, "as_of": "2026-11-04", '
    '"excerpt": "于11月04日网上支付支取人民币9.53元,交易后余额12800.00【中国银行】"}, '
    '"anomalies": []}'
)


def test_parse_plain_json() -> None:
    observation = parse_observation_response(RAW)

    assert observation.balance.value == 12800
    assert observation.balance.as_of == DAY
    assert "交易后余额12800.00" in observation.balance.excerpt


def test_parse_fenced_and_chatty_json() -> None:
    raw = f"好的，这是结果：\n```json\n{RAW}\n```\n还需要别的吗？"

    observation = parse_observation_response(raw)

    assert observation.balance.value == 12800


def test_parse_rejects_empty_and_garbage() -> None:
    with pytest.raises(ValueError):
        parse_observation_response("")
    with pytest.raises(ValueError):
        parse_observation_response("今天花得不多")
    with pytest.raises(ValueError):
        parse_observation_response('{"unrelated": 1}')


def test_parse_accepts_explicit_null_balance() -> None:
    observation = parse_observation_response('{"balance": null, "anomalies": ["素材里没有余额"]}')

    assert observation.balance.value is None
    assert observation.anomalies == ("素材里没有余额",)


def test_verify_accepts_verbatim_excerpt() -> None:
    observation = verify(parse_observation_response(RAW), SMS, DAY)

    assert observation.balance.confidence == "ok"
    assert observation.anomalies == ()


def test_verify_survives_fullwidth_and_spaces() -> None:
    """模型把全角标点改成半角、或多打了空格，不该判成编造。"""
    raw = RAW.replace("交易后余额12800.00", "交易后余额 12800.00").replace("，", ",")

    observation = verify(parse_observation_response(raw), SMS.replace(",", "，"), DAY)

    assert observation.balance.confidence == "ok"


def test_verify_flags_hallucinated_excerpt() -> None:
    raw = RAW.replace("交易后余额12800.00【中国银行】", "交易后余额12800.00【招商银行】")

    observation = verify(parse_observation_response(raw), SMS, DAY)

    assert observation.balance.confidence == "suspect"
    assert any("找不到" in item for item in observation.anomalies)


def test_verify_flags_decimal_point_slip() -> None:
    """小数点错位是最常见的读数错误：1280000 不在摘录里。"""
    raw = RAW.replace('"value": 12800', '"value": 1280000')

    observation = verify(parse_observation_response(raw), SMS, DAY)

    assert observation.balance.confidence == "suspect"
    assert any("对不上" in item for item in observation.anomalies)


def test_verify_flags_missing_excerpt() -> None:
    raw = '{"balance": {"value": 12800, "as_of": "2026-11-04", "excerpt": ""}}'

    observation = verify(parse_observation_response(raw), SMS, DAY)

    assert observation.balance.confidence == "suspect"


def test_verify_defaults_missing_as_of_to_today() -> None:
    raw = '{"balance": {"value": 12800, "as_of": null, "excerpt": "交易后余额12800.00"}}'

    observation = verify(parse_observation_response(raw), SMS, DAY)

    assert observation.balance.as_of == DAY
    assert observation.balance.confidence == "ok"  # 摘录能对上，只是日期没读到
    assert any("日期" in item for item in observation.anomalies)


def test_verify_flags_future_as_of_and_clamps() -> None:
    raw = RAW.replace('"as_of": "2026-11-04"', '"as_of": "2027-01-01"')

    observation = verify(parse_observation_response(raw), SMS, DAY)

    assert observation.balance.confidence == "suspect"
    assert observation.balance.as_of == DAY


def test_verify_keeps_earlier_as_of() -> None:
    """素材里的余额是昨天的，就如实记昨天：它说明今天还没有新交易。"""
    raw = RAW.replace('"as_of": "2026-11-04"', '"as_of": "2026-11-03"')

    observation = verify(parse_observation_response(raw), SMS, DAY)

    assert observation.balance.as_of == "2026-11-03"
    assert observation.balance.confidence == "ok"


def test_verify_without_balance_is_not_suspect() -> None:
    """没读到余额是「不知道」，不是「可疑」；这两种状态不能混。"""
    observation = verify(Observation(), SMS, DAY)

    assert observation.balance.value is None
    assert observation.balance.confidence == "none"


def test_stub_never_invents_a_balance() -> None:
    observation = StubProvider().observe(SMS, DAY)

    assert observation.balance.value is None
    assert observation.balance.confidence == "none"


def test_provider_observe_parses_model_output(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAICompatibleProvider(api_key="fake", model="m", base_url="https://example.com/v1")
    monkeypatch.setattr(provider, "_chat", lambda system, user, temperature=0.7: (RAW, {}))

    observation = provider.observe(SMS, DAY)

    assert observation.balance.value == 12800


def test_provider_observe_wraps_bad_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from step_ledger.judge.base import ProviderError

    provider = OpenAICompatibleProvider(api_key="fake", model="m", base_url="https://example.com/v1")
    monkeypatch.setattr(provider, "_chat", lambda system, user, temperature=0.7: ("随便说点什么", {}))

    with pytest.raises(ProviderError):
        provider.observe(SMS, DAY)


def test_normalize_flattens_width_and_space() -> None:
    assert normalize("交易后余额　１２８００，００") == "交易后余额12800,00"


def test_observe_prompt_carries_materials_and_date() -> None:
    prompt = build_observe_prompt(SMS, DAY)

    assert DAY in prompt
    assert "交易后余额12800.00" in prompt
    assert "只输出 JSON" in prompt


def test_observe_prompt_handles_empty_day() -> None:
    assert "没有留下任何素材" in build_observe_prompt("", DAY)


def test_verify_ignores_extra_balance_fields() -> None:
    raw = '{"balance": {"value": 12800, "currency": "CNY", "excerpt": "交易后余额12800.00"}}'

    observation = verify(parse_observation_response(raw), SMS, DAY)

    assert observation.balance == BalanceObs(
        value=12800, as_of=DAY, excerpt="交易后余额12800.00", confidence="ok"
    )
