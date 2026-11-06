"""次日清点：昨天被追加了内容，今天跑之前先把昨天定格。

几条硬约束在这里被钉死：
- 内容没变 → 0 次模型调用、一个字节都不重写
- 素材变了 → 重判那一天，但**不播报**
- 素材被清理 → 只补事实，不覆盖原文
- 模型挂了 → 宁可不清，也不拿模板话覆盖好文本
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from step_ledger.collect.adapters.manual import fingerprint
from step_ledger.pipeline import run, settle
from step_ledger.shared.config import Config
from step_ledger.shared.types import BalanceObs, Facts, GoalFacts, Judgment, Observation

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


class FakeProvider:
    """按日期给余额；记录每一次调用，方便断言「没花 token」。"""

    name = "fake"

    def __init__(self, balances: dict[str, int] | None = None) -> None:
        self.balances = balances or {}
        self.calls: list[tuple[str, str]] = []

    def observe(self, materials_text: str, date: str = "") -> Observation:
        self.calls.append(("observe", date))
        return Observation(
            balance=BalanceObs(
                value=self.balances.get(date), as_of=date, excerpt="余额", confidence="ok"
            )
        )

    def speak(self, materials_dir: Path, profile, date: str = "", facts=None, trend=None) -> Judgment:
        self.calls.append(("speak", date))
        return Judgment(summary=f"清点稿 {date}", advice="清点建议", prompt="p")


class BrokenProvider(FakeProvider):
    def observe(self, materials_text: str, date: str = "") -> Observation:
        self.calls.append(("observe", date))
        raise RuntimeError("网关 502")


def _facts(day: str, balance: int | None) -> Facts:
    return Facts(
        date=day,
        balance=BalanceObs(value=balance, as_of=day, confidence="ok" if balance else "none"),
        goal=GoalFacts(target=1_000_000, savings=200_000, savings_source="profile"),
    )


def _seed(
    cfg: Config,
    day: str,
    *,
    balance: int | None = 12_000,
    digest: str | None = None,
    material: str | None = "旧内容",
    facts: bool = True,
    summary: str = "当初写的",
) -> Path:
    archive = cfg.archive_for(day)
    archive.mkdir(parents=True, exist_ok=True)
    materials = cfg.materials_for(day)
    materials.mkdir(parents=True, exist_ok=True)
    if material is not None:
        (materials / "sms.txt").write_text(material, encoding="utf-8")
    judgment = Judgment(
        summary=summary,
        advice="当初的建议",
        facts=_facts(day, balance) if facts else None,
        runtime={"materials_digest": digest} if digest else {},
    )
    (archive / "judgment.json").write_text(
        json.dumps(judgment.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    return materials


def _profile(cfg: Config) -> None:
    cfg.profile_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.profile_path.write_text(
        "- 目标：100 万\n- 当前存款：20 万\n"
        "- 约定：目标日期 = 2030-12\n- 约定：月收入 = 16000\n- 约定：公积金月缴存 = 3468\n",
        encoding="utf-8",
    )


def _patch(monkeypatch: pytest.MonkeyPatch, provider) -> None:
    import step_ledger.pipeline as pipeline

    monkeypatch.setattr(pipeline, "_build_provider", lambda cfg, name: provider)


def test_fingerprint_changes_with_content(tmp_path: Path) -> None:
    first = tmp_path / "m1"
    first.mkdir()
    (first / "a.txt").write_text("一行", encoding="utf-8")
    (first / "b.txt").write_text("另一行", encoding="utf-8")
    second = tmp_path / "m2"
    second.mkdir()
    (second / "b.txt").write_text("另一行", encoding="utf-8")
    (second / "a.txt").write_text("一行", encoding="utf-8")

    same = fingerprint(first)
    (first / "a.txt").write_text("一行，又加了一笔", encoding="utf-8")

    assert fingerprint(second) == same  # 与文件顺序无关
    assert fingerprint(first) != same


def test_unchanged_spends_no_tokens_and_writes_nothing(cfg: Config, monkeypatch) -> None:
    materials = _seed(cfg, YESTERDAY)
    _seed(cfg, YESTERDAY, digest=fingerprint(materials), material=None)
    before = (cfg.archive_for(YESTERDAY) / "judgment.json").read_bytes()
    provider = FakeProvider()
    _patch(monkeypatch, provider)

    outcome = settle(cfg=cfg, day=YESTERDAY)

    assert outcome.status == "unchanged"
    assert provider.calls == []
    assert (cfg.archive_for(YESTERDAY) / "judgment.json").read_bytes() == before


def test_appended_material_is_rejudged(cfg: Config, monkeypatch) -> None:
    materials = _seed(cfg, YESTERDAY)
    digest = fingerprint(materials)
    _seed(cfg, YESTERDAY, digest=digest, material=None)
    with (materials / "sms.txt").open("a", encoding="utf-8") as handle:
        handle.write("\n20:30 又刷了一笔")
    provider = FakeProvider({YESTERDAY: 11_800})
    _patch(monkeypatch, provider)

    outcome = settle(cfg=cfg, day=YESTERDAY)

    assert outcome.status == "updated"
    assert ("observe", YESTERDAY) in provider.calls
    data = json.loads((cfg.archive_for(YESTERDAY) / "judgment.json").read_text(encoding="utf-8"))
    assert data["facts"]["balance"]["value"] == 11_800
    assert data["runtime"]["materials_digest"] == fingerprint(materials)
    assert data["runtime"]["settled"]["rewrote_prose"] is True
    assert data["summary"] == f"清点稿 {YESTERDAY}"


def test_settlement_never_broadcasts(cfg: Config, monkeypatch) -> None:
    materials = _seed(cfg, YESTERDAY)
    _seed(cfg, YESTERDAY, digest=fingerprint(materials), material=None)
    with (materials / "sms.txt").open("a", encoding="utf-8") as handle:
        handle.write("\n晚一点")
    cfg = Config(**{**cfg.__dict__, "channels": ("console", "pet")})
    _patch(monkeypatch, FakeProvider({YESTERDAY: 11_800}))

    settle(cfg=cfg, day=YESTERDAY)

    archive = cfg.archive_for(YESTERDAY)
    assert (archive / "report.md").is_file()  # 记录更新
    assert not (archive / "pet_task.md").exists()  # 但不播报


def test_cleaned_materials_only_backfill_legacy_facts(cfg: Config, monkeypatch) -> None:
    _seed(cfg, YESTERDAY, facts=False, material=None)
    provider = FakeProvider()
    _patch(monkeypatch, provider)

    outcome = settle(cfg=cfg, day=YESTERDAY)

    assert outcome.status == "updated"
    assert outcome.reason == "只补事实，保留原文"
    assert provider.calls == []  # 没有素材，绝不调模型
    data = json.loads((cfg.archive_for(YESTERDAY) / "judgment.json").read_text(encoding="utf-8"))
    assert data["summary"] == "当初写的"
    assert data["facts"]["backfilled"] is True
    assert data["runtime"]["settled"]["rewrote_prose"] is False


def test_cleaned_materials_keep_existing_facts(cfg: Config, monkeypatch) -> None:
    """已经有事实的日子，素材被清理后不该用「没有余额」把好数字改坏。"""
    _seed(cfg, YESTERDAY, balance=12_000, digest="old-digest", material=None)
    provider = FakeProvider()
    _patch(monkeypatch, provider)

    outcome = settle(cfg=cfg, day=YESTERDAY)

    assert outcome.status == "skipped"
    data = json.loads((cfg.archive_for(YESTERDAY) / "judgment.json").read_text(encoding="utf-8"))
    assert data["facts"]["balance"]["value"] == 12_000


def test_model_failure_never_overwrites_good_prose(cfg: Config, monkeypatch) -> None:
    materials = _seed(cfg, YESTERDAY)
    old_digest = fingerprint(materials)
    _seed(cfg, YESTERDAY, digest=old_digest, material=None)
    with (materials / "sms.txt").open("a", encoding="utf-8") as handle:
        handle.write("\n晚一点")
    _patch(monkeypatch, BrokenProvider())

    outcome = settle(cfg=cfg, day=YESTERDAY)

    assert outcome.status == "failed"
    data = json.loads((cfg.archive_for(YESTERDAY) / "judgment.json").read_text(encoding="utf-8"))
    assert data["summary"] == "当初写的"
    assert data["runtime"]["materials_digest"] == old_digest  # 没更新，下次还会试


def test_missing_archive_is_skipped(cfg: Config, monkeypatch) -> None:
    _patch(monkeypatch, FakeProvider())

    outcome = settle(cfg=cfg, day=YESTERDAY)

    assert outcome.status == "skipped"
    assert "没有归档" in outcome.reason


def test_daily_run_settles_yesterday_before_today(cfg: Config, monkeypatch) -> None:
    """昨天 20:30 那笔必须记在昨天，不能算到今天头上。"""
    _profile(cfg)
    materials = _seed(cfg, YESTERDAY, balance=12_000)
    _seed(cfg, YESTERDAY, balance=12_000, digest=fingerprint(materials), material=None)
    with (materials / "sms.txt").open("a", encoding="utf-8") as handle:
        handle.write("\n20:30 又刷了一笔 200")
    today_materials = cfg.materials_for(TODAY)
    today_materials.mkdir(parents=True, exist_ok=True)
    (today_materials / "sms.txt").write_text("今天咖啡 20", encoding="utf-8")
    _patch(monkeypatch, FakeProvider({YESTERDAY: 11_800, TODAY: 11_700}))

    result = run(date=TODAY, payload=None, config=cfg, provider="openai", echo=False)

    assert result.settlements[0].day == YESTERDAY
    assert result.settlements[0].status == "updated"
    yesterday = json.loads((cfg.archive_for(YESTERDAY) / "judgment.json").read_text(encoding="utf-8"))
    assert yesterday["facts"]["balance"]["value"] == 11_800
    assert yesterday["summary"] == f"清点稿 {YESTERDAY}"

    assert result.judgment is not None
    assert result.judgment.facts is not None
    assert result.judgment.facts.pace is not None
    # 11_800（清点后的昨天）− 11_700（今天）= 100；没清点就会变成 300
    assert result.judgment.facts.pace.today == 100


def test_settle_failure_does_not_block_today(cfg: Config, monkeypatch) -> None:
    materials = _seed(cfg, YESTERDAY, balance=12_000)
    _seed(cfg, YESTERDAY, digest=fingerprint(materials), material=None)
    with (materials / "sms.txt").open("a", encoding="utf-8") as handle:
        handle.write("\n晚一点")
    today_materials = cfg.materials_for(TODAY)
    today_materials.mkdir(parents=True, exist_ok=True)
    (today_materials / "sms.txt").write_text("今天咖啡 20", encoding="utf-8")

    import step_ledger.pipeline as pipeline

    def _boom(cfg, name):
        raise RuntimeError("没有 key")

    monkeypatch.setattr(pipeline, "_build_provider", _boom)

    result = run(date=TODAY, payload=None, config=cfg, provider="openai", echo=False)

    assert result.settlements[0].status == "failed"
    assert result.judgment is not None  # 今天照常出结果
    assert (cfg.archive_for(TODAY) / "report.md").is_file()
    log = (cfg.archive_for(TODAY) / "render.log").read_text(encoding="utf-8")
    assert "清点" in log
