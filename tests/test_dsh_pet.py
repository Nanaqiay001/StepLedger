import json
from pathlib import Path

from step_ledger.pipeline import run
from step_ledger.render.channels.dsh_pet import (
    DshPetChannel,
    build_dsh_pet_prompt,
    rule_based_pet_status,
)
from step_ledger.shared.config import Config
from step_ledger.shared.profile import Profile
from step_ledger.shared.types import Judgment, RenderContext


def test_build_dsh_pet_prompt():
    judgment = Judgment(summary="打车 20 元", advice="理性消费", degraded=False)
    profile = Profile(path=Path("/tmp/profile.md"), exists=True, target=1_000_000, savings=100_000)
    ctx = RenderContext(
        date="2026-10-28",
        archive_dir=Path("/tmp/archive"),
        profile=profile,
        material_count=1,
    )

    prompt = build_dsh_pet_prompt(judgment, ctx)
    assert "日期: 2026-10-28" in prompt
    assert "最近总结: 打车 20 元" in prompt
    assert "存款进度: 10.0%" in prompt
    assert "降级模式: 否" in prompt


def test_rule_based_pet_status_scenarios():
    profile = Profile(path=Path("/tmp/profile.md"), exists=True, target=1_000_000, savings=18_000)
    ctx = RenderContext(
        date="2026-10-28",
        archive_dir=Path("/tmp/archive"),
        profile=profile,
        material_count=1,
    )

    # 1. 降级状态
    j_degraded = Judgment(summary="测试总结", advice="测试建议", degraded=True)
    status_degraded = rule_based_pet_status(j_degraded, ctx)
    assert status_degraded["mood"] == "thinking"

    # 2. 收入进账
    j_income = Judgment(summary="工资到账 18000 元", advice="小步存钱", degraded=False)
    status_income = rule_based_pet_status(j_income, ctx)
    assert status_income["mood"] == "happy"
    assert status_income["action"] == "jumping"

    # 3. 肉疼超支
    j_overspend = Judgment(summary="今天在大酒楼聚餐花费 2000 元，超支肉疼", advice="控制开支", degraded=False)
    status_overspend = rule_based_pet_status(j_overspend, ctx)
    assert status_overspend["mood"] == "worried"
    assert status_overspend["action"] == "failed"

    # 4. 达成目标
    profile_reached = Profile(path=Path("/tmp/profile.md"), exists=True, target=1_000_000, savings=1_000_000)
    ctx_reached = RenderContext(
        date="2026-10-28",
        archive_dir=Path("/tmp/archive"),
        profile=profile_reached,
        material_count=1,
    )
    j_reached = Judgment(summary="存够 100 万！", advice="享受生活", degraded=False)
    status_reached = rule_based_pet_status(j_reached, ctx_reached)
    assert status_reached["mood"] == "celebrating"


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
    assert (archive_dir / "pet_status.json").is_file()
    assert (archive_dir / "pet.md").is_file()

    status_data = json.loads((archive_dir / "pet_status.json").read_text(encoding="utf-8"))
    assert status_data["pet_name"] == "Aemeath"
    assert status_data["date"] == "2026-10-28"
    assert "mood" in status_data
    assert "action" in status_data
    assert "bubble_text" in status_data


def test_pipeline_with_dsh_pet_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER_CHANNELS", "console,dsh-pet")
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
    assert (result.archive_dir / "pet_status.json").is_file()
    assert (result.archive_dir / "pet.md").is_file()

    render_channels = [r.channel for r in result.renders]
    assert "console" in render_channels
    assert "dsh-pet" in render_channels
