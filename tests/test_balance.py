"""存款兜底：档案没填时用模型识别出的余额，手填的永远优先。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import DATE
from step_ledger.judge.prompt import parse_balance, parse_judgment_response
from step_ledger.pipeline import run
from step_ledger.shared.config import Config
from step_ledger.shared.types import Judgment


class FakeProvider:
    """假的模型：只关心它返回的 balance，用来验证管线侧的处理。"""

    def __init__(self, balance: int | None) -> None:
        self.balance = balance

    def judge(self, materials_dir: Path, profile, date: str = "") -> Judgment:
        return Judgment(
            summary="今天挺稳",
            advice="明天继续记一笔",
            prompt="fake prompt",
            meta={"provider": "fake", "balance": self.balance},
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"summary": "a", "advice": "b", "balance": 12864}', 12864),
        ('{"summary": "a", "advice": "b", "balance": "12,864.09"}', 12864),
        ('{"summary": "a", "advice": "b", "balance": null}', None),
        ('{"summary": "a", "advice": "b"}', None),
    ],
)
def test_balance_comes_from_model_json(raw: str, expected: int | None) -> None:
    assert parse_judgment_response(raw)[2] == expected


def test_parse_balance_is_tolerant() -> None:
    assert parse_balance("¥12,864.09 元") == 12864
    assert parse_balance(12864.4) == 12864
    assert parse_balance(None) is None
    assert parse_balance("没写") is None


def test_empty_profile_uses_model_balance(cfg: Config, monkeypatch) -> None:
    import step_ledger.pipeline as pipeline

    monkeypatch.setattr(pipeline, "_build_provider", lambda cfg, name: FakeProvider(12864))

    run(date=DATE, payload="咖啡 20", provider="openai", config=cfg, echo=False)

    report = (cfg.archive_for(DATE) / "report.md").read_text(encoding="utf-8")
    assert "¥12,864" in report
    assert "AI 从素材识别" in report

    data = json.loads((cfg.archive_for(DATE) / "judgment.json").read_text(encoding="utf-8"))
    assert data["meta"]["progress"]["savings"] == 12864


def test_profile_savings_win_over_model(cfg: Config, monkeypatch) -> None:
    import step_ledger.pipeline as pipeline

    monkeypatch.setattr(pipeline, "_build_provider", lambda cfg, name: FakeProvider(12864))
    cfg.profile_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.profile_path.write_text("- 目标：100 万\n- 当前存款：200000\n", encoding="utf-8")

    run(date=DATE, payload="咖啡 20", provider="openai", config=cfg, echo=False)

    report = (cfg.archive_for(DATE) / "report.md").read_text(encoding="utf-8")
    assert "¥200,000" in report
    assert "AI 从素材识别" not in report

