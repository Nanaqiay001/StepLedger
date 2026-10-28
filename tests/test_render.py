"""渲染层：报告前三行、进度条、里程碑历史、降级标注。"""

from __future__ import annotations

import json
from pathlib import Path

from step_ledger.render.channels.console import ConsoleChannel
from step_ledger.shared.profile import parse_profile
from step_ledger.shared.types import Judgment, RenderContext


def _ctx(tmp_path: Path, profile, **kwargs) -> RenderContext:
    archive = tmp_path / "archive" / "2026-10-28"
    return RenderContext(
        date="2026-10-28",
        archive_dir=archive,
        profile=profile,
        echo=False,
        **kwargs,
    )


def test_report_and_milestones(tmp_path: Path) -> None:
    profile = parse_profile("- 目标：100 万\n- 当前存款：20 万\n", tmp_path / "profile.md")
    ctx = _ctx(tmp_path, profile)
    judgment = Judgment(summary="这两天挺稳的。", advice="明天少点一次外卖。")

    result = ConsoleChannel().render(judgment, ctx)

    report = (ctx.archive_dir / "report.md").read_text(encoding="utf-8")
    assert report.splitlines()[1].startswith("最近怎么样：")
    assert report.splitlines()[2].startswith("下一步怎么走：")
    assert "20.0%" in report
    assert len(result.artifacts) == 2

    milestones = (ctx.archive_dir / "milestones.md").read_text(encoding="utf-8")
    assert "目标里程碑" in milestones


def test_milestones_collects_history(tmp_path: Path) -> None:
    profile = parse_profile("- 目标：100 万\n- 当前存款：20 万\n", tmp_path / "profile.md")
    older = tmp_path / "archive" / "2026-10-27"
    older.mkdir(parents=True)
    (older / "judgment.json").write_text(
        json.dumps({"meta": {"date": "2026-10-27", "progress": {"savings": 100_000, "percent": 0.1}}}),
        encoding="utf-8",
    )

    ctx = _ctx(tmp_path, profile)
    ConsoleChannel().render(Judgment(summary="稳", advice="继续"), ctx)

    milestones = (ctx.archive_dir / "milestones.md").read_text(encoding="utf-8")
    assert "2026-10-27" in milestones
    assert "10.0%" in milestones


def test_degraded_is_labelled(tmp_path: Path) -> None:
    profile = parse_profile("- 目标：100 万\n", tmp_path / "profile.md")
    ctx = _ctx(tmp_path, profile)
    judgment = Judgment(summary="今天没有记录。", advice="明天记一条。", degraded=True)

    ConsoleChannel().render(judgment, ctx)

    assert "降级模式" in (ctx.archive_dir / "report.md").read_text(encoding="utf-8")


def test_missing_profile_still_renders(tmp_path: Path) -> None:
    from step_ledger.shared.profile import load_profile

    profile = load_profile(tmp_path / "profile.md")
    ctx = _ctx(tmp_path, profile, profile_created=True)
    ConsoleChannel().render(Judgment(summary="稳", advice="继续"), ctx)

    report = (ctx.archive_dir / "report.md").read_text(encoding="utf-8")
    assert "第一次见" in report
    assert "暂时画不出进度条" in report
