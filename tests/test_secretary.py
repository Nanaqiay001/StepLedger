"""秘书：观察 → 事实 → 趋势 → 说话，每一步失败都单独降级。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from step_ledger.judge import secretary
from step_ledger.judge.history import History
from step_ledger.judge.providers.stub import StubProvider
from step_ledger.shared.profile import parse_profile
from step_ledger.shared.types import BalanceObs, Judgment, Observation

DAY = "2026-11-04"


class Reader(StubProvider):
    """观察正常、说话用模板：大多数用例的基线。"""

    name = "reader"

    def observe(self, materials_text: str, date: str = "") -> Observation:
        return Observation(
            balance=BalanceObs(value=11400, as_of=date, excerpt="交易后余额11400.00", confidence="ok")
        )


class BrokenProvider(StubProvider):
    """观察必挂，说话正常。"""

    name = "broken-observe"

    def observe(self, materials_text: str, date: str = "") -> Observation:
        raise RuntimeError("网关 502")


class MuteProvider(Reader):
    """观察正常，说话必挂。"""

    name = "mute"

    def judge(self, materials_dir: Path, profile, date: str = "") -> Judgment:
        raise RuntimeError("模型返回不是约定的 JSON")


def _profile(tmp_path: Path, savings: str | None = "20 万"):
    raw = "- 目标：100 万\n"
    if savings:
        raw += f"- 当前存款：{savings}\n"
    raw += "- 约定：目标日期 = 2030-12\n- 约定：月收入 = 16000\n- 约定：公积金月缴存 = 3468\n"
    return parse_profile(raw, tmp_path / "profile.md")


def _materials(tmp_path: Path, text: str | None = "咖啡 20，交易后余额11400.00") -> Path:
    materials = tmp_path / "materials" / DAY
    materials.mkdir(parents=True)
    if text is not None:
        (materials / "sms.txt").write_text(text, encoding="utf-8")
    return materials


def _archive(tmp_path: Path, days: dict[str, int] | None = None) -> History:
    root = tmp_path / "archive"
    for day, balance in (days or {}).items():
        target = root / day
        target.mkdir(parents=True, exist_ok=True)
        (target / "judgment.json").write_text(
            json.dumps({"summary": "s", "advice": "a", "meta": {"date": day, "balance": balance}}),
            encoding="utf-8",
        )
    return History(root, day=DAY)


def _run(tmp_path: Path, provider=None, materials=None):
    return secretary.run(
        materials_dir=materials or _materials(tmp_path),
        profile=_profile(tmp_path),
        date=DAY,
        provider=provider or Reader(),
        history=_archive(tmp_path, {"2026-10-31": 12000, "2026-11-03": 11500}),
        requested="stub",
    )


def test_secretary_attaches_facts_trend_and_observation(tmp_path: Path) -> None:
    judgment = _run(tmp_path)

    assert judgment.facts is not None
    assert judgment.facts.date == DAY
    assert judgment.facts.month is not None
    assert judgment.facts.month.spent == 600  # 12000 − 11400
    assert len(judgment.trend.days) == 14
    assert judgment.prompt.strip()
    assert judgment.is_valid


def test_runtime_is_a_whitelist(tmp_path: Path) -> None:
    judgment = _run(tmp_path)

    assert set(judgment.runtime) <= set(secretary.RUNTIME_KEYS)
    assert judgment.runtime["steps"] == {"observe": "ok", "speak": "ok"}
    assert judgment.runtime["requested_provider"] == "stub"


def test_empty_day_skips_both_model_calls(tmp_path: Path) -> None:
    class NeverCalled(StubProvider):
        def observe(self, materials_text: str, date: str = "") -> Observation:
            raise AssertionError("空素材不该观察")

        def judge(self, materials_dir: Path, profile, date: str = "") -> Judgment:
            raise AssertionError("空素材不该说话")

    judgment = _run(tmp_path, provider=NeverCalled(), materials=_materials(tmp_path, text=None))

    assert judgment.runtime["provider"] == "none"
    assert judgment.runtime["steps"] == {"observe": "skipped", "speak": "stub"}
    assert judgment.degraded is False
    assert "今天没有记录" in judgment.summary


def test_observe_failure_degrades_but_keeps_numbers_from_history(tmp_path: Path) -> None:
    judgment = _run(tmp_path, provider=BrokenProvider())

    assert judgment.degraded is True
    assert "观察失败" in judgment.runtime["degraded_reason"]
    assert judgment.runtime["steps"]["observe"] == "failed"
    assert judgment.runtime["steps"]["speak"] == "ok"
    assert judgment.facts is not None
    assert judgment.facts.month is not None
    assert judgment.facts.month.spent == 500  # 退回 11-03 的余额
    assert judgment.facts.month.spent_as_of == "2026-11-03"


def test_speak_failure_falls_back_to_stub_but_facts_stay_authoritative(tmp_path: Path) -> None:
    judgment = _run(tmp_path, provider=MuteProvider())

    assert judgment.degraded is True
    assert "说话失败" in judgment.runtime["degraded_reason"]
    assert judgment.runtime["steps"]["speak"] == "failed"
    assert judgment.facts is not None
    assert judgment.facts.balance.value == 11400  # 观测仍然被采纳
    assert judgment.summary.strip()


def test_suspect_observation_is_kept_and_flagged(tmp_path: Path) -> None:
    """模型编的摘录不该让整条管线失败，但必须留下痕迹。"""
    class Liar(StubProvider):
        def observe(self, materials_text: str, date: str = "") -> Observation:
            return Observation(
                balance=BalanceObs(value=11400, as_of=date, excerpt="不存在的原文", confidence="ok")
            )

    judgment = _run(tmp_path, provider=Liar())

    assert judgment.observation.balance.confidence == "suspect"
    assert judgment.facts is not None
    assert judgment.facts.balance.confidence == "suspect"
    assert judgment.degraded is False  # 可疑不等于失败


def test_backfill_keeps_written_prose(tmp_path: Path) -> None:
    original = Judgment(summary="当初写的", advice="当初的建议", prompt="old prompt")
    original.runtime = {"provider": "openai"}

    filled = secretary.backfill(
        judgment=original,
        profile=_profile(tmp_path),
        date=DAY,
        history=_archive(tmp_path, {"2026-10-31": 12000, "2026-11-03": 11500}),
    )

    assert filled.summary == "当初写的"
    assert filled.advice == "当初的建议"
    assert filled.facts is not None
    assert filled.facts.backfilled is True
    assert filled.facts.month is not None
    assert filled.facts.month.spent == 500
    assert filled.runtime["facts_backfilled"] is True
    assert filled.runtime["provider"] == "openai"  # 原来的来源没被覆盖


def test_backfilled_flag_marks_past_days(tmp_path: Path) -> None:
    judgment = secretary.run(
        materials_dir=_materials(tmp_path),
        profile=_profile(tmp_path),
        date=DAY,
        provider=StubProvider(),
        history=_archive(tmp_path, {"2026-10-31": 12000}),
        backfilled=True,
    )

    assert judgment.facts is not None
    assert judgment.facts.backfilled is True


def test_profile_created_is_carried(tmp_path: Path) -> None:
    judgment = secretary.run(
        materials_dir=_materials(tmp_path),
        profile=_profile(tmp_path),
        date=DAY,
        provider=StubProvider(),
        history=_archive(tmp_path, {}),
        profile_created=True,
    )

    assert judgment.runtime["profile_created"] is True
