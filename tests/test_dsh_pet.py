from pathlib import Path

from step_ledger.pipeline import run
from step_ledger.render.channels.dsh_pet import (
    DshPetChannel,
    build_dsh_prompt,
)
from step_ledger.shared.config import Config
from step_ledger.shared.profile import Profile
from step_ledger.shared.types import Judgment, RenderContext


def test_build_dsh_prompt():
    judgment = Judgment(summary="打车 20 元", advice="理性消费", degraded=False)
    profile = Profile(path=Path("/tmp/profile.md"), exists=True, target=1_000_000, savings=100_000)
    ctx = RenderContext(
        date="2026-10-28",
        archive_dir=Path("/tmp/archive"),
        profile=profile,
        material_count=1,
    )

    prompt = build_dsh_prompt(judgment, ctx)
    assert "【StepLedger 每日复盘】" in prompt
    assert "日期：2026-10-28" in prompt
    assert "总结：打车 20 元" in prompt
    assert "建议：理性消费" in prompt
    assert "进度：10.0%" in prompt
    assert "调用 pet_say 工具" in prompt


def test_dsh_pet_channel_render(tmp_path):
    archive_dir = tmp_path / "archive" / "2026-10-28"
    archive_dir.mkdir(parents=True)

    judgment = Judgment(summary="中午快餐 30 元", advice="继续按计划记账", degraded=False)
    profile = Profile(path=tmp_path / "profile.md", exists=True, target=1_000_000, savings=50_000)
    ctx = RenderContext(
        date="2026-10-28",
        archive_dir=archive_dir,
        profile=profile,
        material_count=1,
        echo=False,
    )

    channel = DshPetChannel()
    result = channel.render(judgment, ctx)

    assert result.channel == "dsh-pet"
    assert (archive_dir / "dsh_prompt.md").is_file()
    assert (archive_dir / "pet.md").is_file()

    prompt_text = (archive_dir / "dsh_prompt.md").read_text(encoding="utf-8")
    assert "总结：中午快餐 30 元" in prompt_text
    assert "建议：继续按计划记账" in prompt_text
    assert "pet_say" in prompt_text

    pet_md_text = (archive_dir / "pet.md").read_text(encoding="utf-8")
    assert "跬步账复盘摘要 (dsh-pet)" in pet_md_text
    assert "最近总结：中午快餐 30 元" in pet_md_text


def test_pipeline_with_dsh_pet_channel_no_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER_CHANNELS", "console,dsh-pet")
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)
    cfg = Config.load(tmp_path)

    result = run(
        date="2026-10-28",
        payload="午饭 35 元",
        root=tmp_path,
        config=cfg,
        echo=False,
    )

    assert result.archive_dir.is_dir()
    assert (result.archive_dir / "report.md").is_file()
    assert (result.archive_dir / "dsh_prompt.md").is_file()
    assert (result.archive_dir / "pet.md").is_file()

    render_channels = [r.channel for r in result.renders]
    assert "console" in render_channels
    assert "dsh-pet" in render_channels
