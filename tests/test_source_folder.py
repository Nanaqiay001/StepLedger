"""自动素材夹：只收当天的、重复收不产生副本、缺目录不中断。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from conftest import DATE
from step_ledger.collect.adapters.folder import collect
from step_ledger.pipeline import run
from step_ledger.shared.config import Config

BILL = "{2026-10-28T11:36:45+08:00}-{您的借记卡于10月28日银联入账人民币15.00元，交易后余额12897.77}\n"


def _inbox(tmp_path: Path) -> Path:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "20261028.txt").write_text(BILL, encoding="utf-8")
    (inbox / "20261027.txt").write_text("昨天的记录\n", encoding="utf-8")
    (inbox / ".DS_Store").write_bytes(b"\x00")
    return inbox


def test_only_the_run_date_is_collected(tmp_path: Path) -> None:
    result = collect(tmp_path / DATE, _inbox(tmp_path), DATE)

    assert len(result.files) == 1
    assert result.files[0].name.startswith("20261028-")
    assert "入账人民币15.00元" in result.files[0].read_text(encoding="utf-8")
    assert result.skipped == []


def test_same_source_is_idempotent(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path)
    materials = tmp_path / DATE

    first = collect(materials, inbox, DATE)
    second = collect(materials, inbox, DATE)

    assert len(first.added) == 1
    assert second.added == []


def test_iso_date_in_name_is_understood(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "账单-2026-10-28.txt").write_text("咖啡 18\n", encoding="utf-8")

    assert len(collect(tmp_path / DATE, inbox, DATE).files) == 1


def test_mtime_is_used_when_name_has_no_date(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    note = inbox / "随手记.txt"
    note.write_text("打车 22\n", encoding="utf-8")
    stamp = datetime(2026, 10, 28, 9, 30).timestamp()
    os.utime(note, (stamp, stamp))

    assert len(collect(tmp_path / DATE, inbox, DATE).files) == 1


def test_unsupported_files_are_skipped(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "20261028.png").write_bytes(b"\x89PNG\r\n")

    result = collect(tmp_path / DATE, inbox, DATE)
    assert result.files == []
    assert any("不支持的格式" in item for item in result.skipped)


def test_missing_source_is_reported_not_fatal(tmp_path: Path) -> None:
    result = collect(tmp_path / DATE, tmp_path / "not-there", DATE)

    assert result.files == []
    assert any("素材夹不存在" in item for item in result.skipped)


def test_source_dirs_are_comma_separated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COLLECT_SOURCE_DIRS", "a, ./b")

    cfg = Config.load(tmp_path)

    assert cfg.source_dirs == ((tmp_path / "a").resolve(), (tmp_path / "b").resolve())


def test_pipeline_reads_configured_source(tmp_path: Path, monkeypatch) -> None:
    inbox = _inbox(tmp_path)
    monkeypatch.setenv("COLLECT_SOURCE_DIRS", str(inbox))
    cfg = Config.load(tmp_path)

    result = run(date=DATE, config=cfg, echo=False)

    names = [p.name for p in cfg.materials_for(DATE).iterdir() if p.name != "profile.md"]
    assert any(name.startswith("20261028-") for name in names)
    assert result.judgment is not None
    assert "入账人民币15.00元" in result.judgment.prompt


def test_explicit_source_overrides_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COLLECT_SOURCE_DIRS", str(tmp_path / "not-there"))

    result = run(date=DATE, config=Config.load(tmp_path), sources=[_inbox(tmp_path)], echo=False)

    assert result.judgment is not None
    assert "入账人民币15.00元" in result.judgment.prompt
