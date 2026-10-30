"""采集层：只落盘、幂等、不认格式就跳过。"""

from __future__ import annotations

from pathlib import Path

from step_ledger.collect.adapters.manual import ManualAdapter, collect


def test_text_payload_is_idempotent(tmp_path: Path) -> None:
    materials = tmp_path / "2026-10-28"
    first = collect(materials, "午饭 30 元")
    second = collect(materials, "午饭 30 元")

    assert len(first.added) == 1
    assert second.added == []
    assert len(second.files) == 1
    assert "午饭 30 元" in second.files[0].read_text(encoding="utf-8")


def test_file_payload_is_copied(tmp_path: Path, normal_day: Path) -> None:
    result = collect(tmp_path / "2026-10-28", normal_day / "bill.md")
    assert len(result.files) == 1
    assert "工资到账" in result.files[0].read_text(encoding="utf-8")


def test_directory_payload_skips_unsupported(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "note.md").write_text("记录一条", encoding="utf-8")
    (inbox / "screenshot.png").write_bytes(b"\x89PNG\r\n")

    result = collect(tmp_path / "2026-10-28", inbox)
    assert len(result.files) == 1
    assert any("不支持的格式" in item for item in result.skipped)


def test_profile_is_not_a_material(tmp_path: Path) -> None:
    materials = tmp_path / "2026-10-28"
    materials.mkdir(parents=True)
    (materials / "profile.md").write_text("- 目标：100 万", encoding="utf-8")
    (materials / "note.md").write_text("咖啡 20", encoding="utf-8")

    result = ManualAdapter().collect(materials)
    assert [p.name for p in result.files] == ["note.md"]


def test_empty_payload_still_creates_dir(tmp_path: Path) -> None:
    materials = tmp_path / "2026-10-28"
    result = collect(materials, None)
    assert materials.is_dir()
    assert result.files == []
