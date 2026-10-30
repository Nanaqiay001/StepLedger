"""Layer 1 冒烟 + Layer 2 契约：整条管线跑通，且归档符合约定。"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import DATE
from step_ledger.pipeline import run
from step_ledger.shared.config import Config


def _artifacts(cfg: Config, date: str = DATE) -> Path:
    return cfg.archive_for(date)


def test_end_to_end_archives_everything(cfg: Config, normal_day: Path) -> None:
    result = run(date=DATE, payload=normal_day / "bill.md", config=cfg, echo=False)

    archive = _artifacts(cfg)
    for name in ("prompt.md", "judgment.json", "report.md", "milestones.md"):
        assert (archive / name).is_file(), f"缺少归档产物：{name}"

    materials = cfg.materials_for(DATE)
    assert materials.is_dir()
    assert any(materials.glob("*.md"))
    assert cfg.profile_path.is_file()

    assert result.judgment is not None
    assert result.judgment.summary.strip()
    assert result.judgment.advice.strip()
    assert result.judgment.meta["date"] == DATE
    assert "午饭外卖" in result.judgment.prompt


def test_report_speaks_first_three_lines(cfg: Config, normal_day: Path) -> None:
    run(date=DATE, payload=normal_day / "bill.md", config=cfg, echo=False)
    report = (_artifacts(cfg) / "report.md").read_text(encoding="utf-8")
    head = "\n".join(report.splitlines()[:3])
    assert "最近怎么样" in head
    assert "下一步怎么走" in head


def test_judgment_json_contract(cfg: Config, normal_day: Path) -> None:
    run(date=DATE, payload=normal_day / "bill.md", config=cfg, echo=False)
    data = json.loads((_artifacts(cfg) / "judgment.json").read_text(encoding="utf-8"))
    assert data["summary"].strip()
    assert data["advice"].strip()
    assert isinstance(data["degraded"], bool)
    assert data["meta"]["progress"]["target"] == 1_000_000


def test_same_day_rerun_is_idempotent(cfg: Config, normal_day: Path) -> None:
    run(date=DATE, payload=normal_day / "bill.md", config=cfg, echo=False)
    first_files = sorted(p.name for p in cfg.materials_for(DATE).iterdir())
    first_archive = sorted(p.name for p in _artifacts(cfg).iterdir())

    run(date=DATE, payload=normal_day / "bill.md", config=cfg, echo=False)
    assert sorted(p.name for p in cfg.materials_for(DATE).iterdir()) == first_files
    assert sorted(p.name for p in _artifacts(cfg).iterdir()) == first_archive
    assert [p.name for p in cfg.archive_dir.iterdir()] == [DATE]


def test_empty_day_is_honest(cfg: Config) -> None:
    result = run(date=DATE, config=cfg, echo=False)
    assert result.judgment is not None
    assert "今天没有记录" in result.judgment.summary
    assert result.judgment.advice.strip()
    assert (_artifacts(cfg) / "judgment.json").is_file()


def test_agent_style_natural_language_payload(cfg: Config) -> None:
    """判断层不只认目录，也认 agent 直接递来的一段话。"""
    result = run(date=DATE, payload="午饭 35，晚上加班打车 22", config=cfg, echo=False)
    assert result.judgment is not None
    assert "午饭 35" in result.judgment.prompt


def test_failed_provider_falls_back_and_flags_degraded(cfg: Config, normal_day: Path) -> None:
    """配了 openai 但没 key → 用模板兜底，并明确标注降级。"""
    result = run(date=DATE, payload=normal_day / "bill.md", config=cfg, provider="openai", echo=False)
    assert result.judgment is not None
    assert result.judgment.degraded is True
    report = (_artifacts(cfg) / "report.md").read_text(encoding="utf-8")
    assert "降级模式" in report


def test_render_stage_refreshes_progress_snapshot(cfg: Config, normal_day: Path) -> None:
    """改了存款后只重跑渲染，judgment 与里程碑都要跟上，不能留旧快照。"""
    run(date=DATE, payload=normal_day / "bill.md", config=cfg, echo=False)
    cfg.profile_path.write_text("- 目标：100 万\n- 当前存款：12 万\n", encoding="utf-8")

    run(date=DATE, stage="render", config=cfg, echo=False)

    data = json.loads((_artifacts(cfg) / "judgment.json").read_text(encoding="utf-8"))
    assert data["meta"]["progress"]["savings"] == 120_000
    milestones = (_artifacts(cfg) / "milestones.md").read_text(encoding="utf-8")
    assert "¥120,000" in milestones


def test_stages_are_resumable(cfg: Config) -> None:
    run(date=DATE, payload="今天买了咖啡 20", stage="collect", config=cfg, echo=False)
    assert cfg.materials_for(DATE).is_dir()
    assert not _artifacts(cfg).exists()

    run(date=DATE, stage="judge", config=cfg, echo=False)
    assert (_artifacts(cfg) / "judgment.json").is_file()
    assert not (_artifacts(cfg) / "report.md").exists()

    run(date=DATE, stage="render", config=cfg, echo=False)
    assert (_artifacts(cfg) / "report.md").is_file()
    assert (_artifacts(cfg) / "milestones.md").is_file()
