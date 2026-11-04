"""存款兜底：档案没填时用观察到的余额，手填的永远优先。

余额现在由观察步给出（只读数、不评价），落进 `facts.goal`；说话步不再产出金额。
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import DATE
from step_ledger.pipeline import run
from step_ledger.shared.config import Config
from step_ledger.shared.types import BalanceObs, Judgment, Observation


class FakeProvider:
    """假的模型：观察给一个余额，说话给固定两句话。"""

    def __init__(self, balance: int | None) -> None:
        self.balance = balance

    def observe(self, materials_text: str, date: str = "") -> Observation:
        return Observation(
            balance=BalanceObs(value=self.balance, as_of=date, excerpt="余额12864", confidence="ok")
        )

    def speak(self, materials_dir: Path, profile, date: str = "", facts=None, trend=None) -> Judgment:
        return Judgment(
            summary="今天挺稳",
            advice="明天继续记一笔",
            prompt="fake prompt",
            runtime={"provider": "fake"},
        )


def test_empty_profile_uses_observed_balance(cfg: Config, monkeypatch) -> None:
    import step_ledger.pipeline as pipeline

    monkeypatch.setattr(pipeline, "_build_provider", lambda cfg, name: FakeProvider(12864))

    run(date=DATE, payload="咖啡 20，余额 12864", provider="openai", config=cfg, echo=False)

    report = (cfg.archive_for(DATE) / "report.md").read_text(encoding="utf-8")
    assert "¥12,864" in report
    assert "AI 从素材识别" in report

    data = json.loads((cfg.archive_for(DATE) / "judgment.json").read_text(encoding="utf-8"))
    assert data["facts"]["goal"]["savings"] == 12864
    assert data["facts"]["goal"]["savings_source"] == "balance"


def test_profile_savings_win_over_observation(cfg: Config, monkeypatch) -> None:
    import step_ledger.pipeline as pipeline

    monkeypatch.setattr(pipeline, "_build_provider", lambda cfg, name: FakeProvider(12864))
    cfg.profile_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.profile_path.write_text("- 目标：100 万\n- 当前存款：200000\n", encoding="utf-8")

    run(date=DATE, payload="咖啡 20，余额 12864", provider="openai", config=cfg, echo=False)

    report = (cfg.archive_for(DATE) / "report.md").read_text(encoding="utf-8")
    assert "¥200,000" in report
    assert "AI 从素材识别" not in report

    data = json.loads((cfg.archive_for(DATE) / "judgment.json").read_text(encoding="utf-8"))
    assert data["facts"]["goal"]["savings_source"] == "profile"


def test_no_balance_and_no_profile_says_unknown(cfg: Config, monkeypatch) -> None:
    import step_ledger.pipeline as pipeline

    monkeypatch.setattr(pipeline, "_build_provider", lambda cfg, name: FakeProvider(None))

    run(date=DATE, payload="午饭 30", provider="openai", config=cfg, echo=False)

    data = json.loads((cfg.archive_for(DATE) / "judgment.json").read_text(encoding="utf-8"))
    assert data["facts"]["goal"]["savings"] is None
    assert data["facts"]["goal"]["savings_source"] == "none"
    assert "未填写" in (cfg.archive_for(DATE) / "report.md").read_text(encoding="utf-8")
