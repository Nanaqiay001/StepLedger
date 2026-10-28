from __future__ import annotations

from pathlib import Path

import pytest

from step_ledger.shared.config import ENV_KEYS, Config

FIXTURES = Path(__file__).parent / "fixtures"
DATE = "2026-10-28"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试不受本机 .env / 环境变量影响。"""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("STEP_LEDGER_ROOT", raising=False)


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config.load(tmp_path)


@pytest.fixture
def normal_day() -> Path:
    return FIXTURES / "normal_day"
