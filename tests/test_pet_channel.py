"""桌宠渠道：简报产出、机械层协议、档位推荐与降级。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

from step_ledger.pipeline import run
from step_ledger.render.channels.pet import (
    BUBBLE_LIMIT,
    DEFAULT_TIERS,
    PetChannel,
    PetClient,
    bubble_text,
    build_brief,
    pick_animation,
    recent_said,
    record_said,
    style_for,
    tiers_from,
)
from step_ledger.shared.config import Config
from step_ledger.shared.profile import parse_profile
from step_ledger.shared.types import Judgment, RenderContext

BASE = "http://127.0.0.1:9/dsh-pet-7340"
def _load_pet_daily():
    spec = importlib.util.spec_from_file_location("pet_daily", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return 200

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


class FakePet:
    """假 dsh-pet：记录每一个请求，按路径回包。"""

    def __init__(
        self,
        *,
        display: str = "desktop",
        lock: bool = True,
        anim: bool = True,
        playback: str = "ended",
        fail_at: int | None = None,
        echo: bool = True,
    ) -> None:
        self.display = display
        self.lock = lock
        self.anim = anim
        self.playback = playback
        self.fail_at = fail_at
        self.echo = echo
        self.last_text: str | None = None
        self.calls: list[dict] = []
        self.sleeps: list[float] = []

    def __call__(self, request, timeout: float | None = None):
        parts = urllib.parse.urlsplit(request.full_url)
        self.calls.append(
            {
                "method": request.get_method(),
                "path": parts.path,
                "query": dict(urllib.parse.parse_qsl(parts.query)),
                "body": json.loads(request.data.decode("utf-8")) if request.data else None,
                "timeout": timeout,
            }
        )
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            raise urllib.error.URLError("connection refused")
        return _Response(self._route(parts.path))

    def _route(self, path: str) -> dict:
        if path.endswith("/config"):
            return {
                "main": {
                    "pets": [{"id": "main", "display": self.display}],
                    "animations": {
                        "idle": ["待机呼吸"],
                        "events": {"balance": ["余额-钱袋满溢"], "whisper": ["碎碎念-发呆"]},
                        "moves": {"default": {"minDist": 60}, "actions": [{"name": "螃蟹走路"}]},
                        "categories": [{"id": "小动作", "weight": 20, "actions": ["照镜子"]}],
                    },
                    "memes": {"要不直接骂他": "适合吐槽"},
                }
            }
        if path.endswith("/state"):
            text = self.last_text if self.echo else "别的话"
            return {"pets": {"main": {"say": {"data": {"text": text}}}}}
        if path.endswith("/lock/release"):
            return {"ok": True}
        if path.endswith("/lock"):
            return {"ok": True, "lockId": "lk-test"} if self.lock else {"ok": False, "reason": "locked"}
        if path.endswith("/broadcast"):
            body = self.calls[-1]["body"] or {}
            self.last_text = body.get("text")
            return {"ok": True}
        if path.endswith("/anim"):
            return {"ok": True, "playbackId": "pb-test"} if self.anim else {"ok": False, "reason": "unknown-animation"}
        if "/playback/" in path:
            return {"playbackId": "pb-test", "status": self.playback}
        raise AssertionError(f"未预期的请求：{path}")

    @property
    def paths(self) -> list[str]:
        return [call["path"] for call in self.calls]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakePet:
    pet = FakePet()
    monkeypatch.setattr("urllib.request.urlopen", pet)
    monkeypatch.setattr(time, "sleep", lambda seconds: pet.sleeps.append(seconds))
    return pet


def _judgment(summary: str = "今天工资到账，账面上先亮了一下。", advice: str = "先把一小笔挪走。") -> Judgment:
    return Judgment(summary=summary, advice=advice)


def _ctx(tmp_path: Path, savings: int = 200_000) -> RenderContext:
    profile = parse_profile(f"- 目标：100 万\n- 当前存款：{savings}\n", tmp_path / "profile.md")
    return RenderContext(
        date="2026-10-28",
        archive_dir=tmp_path / "archive" / "2026-10-28",
        profile=profile,
        material_count=2,
        echo=False,
    )


# ── 文案与档位 ──────────────────────────────────────────────────


def test_bubble_text_takes_first_sentence() -> None:
    assert bubble_text("最近挺稳的。明天可以更省一点。") == "最近挺稳的。"
    assert bubble_text("今天花得有点猛！明天收着点。") == "今天花得有点猛！"
    assert bubble_text("  没有标点的一句话  ") == "没有标点的一句话"
    assert bubble_text("   ") == ""


def test_bubble_text_clips_at_punctuation() -> None:
    summary = (
        "今天工资到账了，账面上先亮了一下，然后交房租、买日用品、还请了一顿饭，"
        "晚上又添置了两件换季衣服，还给猫买了猫粮和新玩具，整体节奏还行。"
    )
    text = bubble_text(summary)
    assert len(text) <= BUBBLE_LIMIT + 1
    assert text.endswith("…")


def test_tiers_from() -> None:
    assert tiers_from("") == DEFAULT_TIERS
    assert tiers_from("off") == ()
    assert tiers_from("a,b") == DEFAULT_TIERS
    assert tiers_from("a, b, c, d, e") == ("a", "b", "c", "d", "e")


def test_pick_animation_tiers() -> None:
    assert pick_animation(0.1, DEFAULT_TIERS) == DEFAULT_TIERS[0]
    assert pick_animation(0.3, DEFAULT_TIERS) == DEFAULT_TIERS[1]
    assert pick_animation(0.6, DEFAULT_TIERS) == DEFAULT_TIERS[2]
    assert pick_animation(0.8, DEFAULT_TIERS) == DEFAULT_TIERS[3]
    assert pick_animation(1.0, DEFAULT_TIERS) == DEFAULT_TIERS[4]
    assert pick_animation(None, DEFAULT_TIERS) is None
    assert pick_animation(0.5, ()) is None


# ── 简报（渲染层交给 agent 的东西）──────────────────────────────


def test_brief_carries_facts_and_command(tmp_path: Path) -> None:
    brief = build_brief(_judgment(), _ctx(tmp_path), base_url=BASE, pet_id="main")

    assert "今天工资到账" in brief          # 事实
    assert "先把一小笔挪走" in brief
    assert "20.0%" in brief
    assert "scripts/pet_play.py --text" in brief
    assert "脚本" in brief                   # 明确让 agent 用脚本，别拼 HTTP
    assert DEFAULT_TIERS[0] in brief         # 20% 的推荐档位
    assert BASE in brief


def test_brief_warns_on_degraded(tmp_path: Path) -> None:
    judgment = _judgment()
    judgment.degraded = True
    brief = build_brief(judgment, _ctx(tmp_path), base_url=BASE, pet_id="main")
    assert "降级" in brief


def test_brief_has_no_sample_line_and_rotates_style(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    brief = build_brief(_judgment(), ctx, base_url=BASE, pet_id="main")

    assert "今天的口吻" in brief
    assert "示例台词" in brief                      # 明确告诉 agent 别照抄
    assert "先留一小份不动" not in brief            # 不再给现成句子
    assert style_for("2026-10-30") != style_for("2026-10-31")


def test_brief_lists_recent_lines(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    record_said(ctx.archive_dir.parent / "2026-10-29", "昨天那句", "照镜子")

    brief = build_brief(_judgment(), ctx, base_url=BASE, pet_id="main")

    assert "昨天那句" in brief
    assert recent_said(ctx.archive_dir) == ["昨天那句（照镜子）"]


def test_record_said_appends(tmp_path: Path) -> None:
    record_said(tmp_path, "第一句", "收红包")
    record_said(tmp_path, "第二句")

    text = (tmp_path / "pet_said.md").read_text(encoding="utf-8")
    assert text.splitlines() == ["- 第一句（收红包）", "- 第二句"]


def test_channel_writes_task_and_makes_no_requests(tmp_path: Path, fake: FakePet) -> None:
    result = PetChannel(BASE).render(_judgment(), _ctx(tmp_path))

    assert fake.calls == []                       # 渲染层不直接控制宠物
    assert result.artifacts[0].name == "pet_task.md"
    assert "pet_play.py" in result.artifacts[0].read_text(encoding="utf-8")


def test_channel_hints_once_when_echo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ctx = _ctx(tmp_path)
    ctx.echo = True
    PetChannel(BASE).render(_judgment(), ctx)

    out = capsys.readouterr().out
    assert out.count("桌宠简报") == 1
    assert "pet_play.py" in out


def test_channel_skips_without_base_url(tmp_path: Path, fake: FakePet) -> None:
    result = PetChannel().render(_judgment(), _ctx(tmp_path))

    assert fake.calls == []
    assert "未配置" in result.output
    assert not (tmp_path / "archive" / "2026-10-28" / "pet_task.md").exists()


def test_channel_silent_on_empty_day(tmp_path: Path, fake: FakePet) -> None:
    ctx = _ctx(tmp_path)
    ctx.material_count = 0

    result = PetChannel(BASE).render(_judgment(), ctx)

    assert "没有素材" in result.output
    assert not (tmp_path / "archive" / "2026-10-28" / "pet_task.md").exists()


def test_channel_rejects_non_loopback(tmp_path: Path, fake: FakePet) -> None:
    result = PetChannel("http://example.com/dsh-pet-7340").render(_judgment(), _ctx(tmp_path))

    assert "本机" in result.output
    assert not (tmp_path / "archive" / "2026-10-28" / "pet_task.md").exists()


# ── 机械层（agent 调用的脚本背后）──────────────────────────────


def test_catalog_lists_animations_and_memes(fake: FakePet) -> None:
    animations, memes = PetClient(BASE).catalog()

    assert "待机呼吸" in animations
    assert "螃蟹走路" in animations
    assert "照镜子" in animations
    assert "小动作" not in animations       # 分类名不是动画
    assert memes == {"要不直接骂他": "适合吐槽"}


def test_play_sequence(fake: FakePet) -> None:
    ok, detail = PetClient(BASE).play("先留一小份不动", animation="余额-数金皱眉")

    assert ok, detail
    assert fake.paths == [
        "/dsh-pet-7340/config",
        "/dsh-pet-7340/lock",
        "/dsh-pet-7340/broadcast",
        "/dsh-pet-7340/anim",
        "/dsh-pet-7340/playback/pb-test",
        "/dsh-pet-7340/lock/release",
        "/dsh-pet-7340/state",
    ]
    lock, say, anim, playback, release = fake.calls[1:6]
    assert lock["body"] == {"ttl": 30_000}
    assert say["body"] == {"text": "先留一小份不动", "anim": False}
    assert anim["body"] == {"name": "余额-数金皱眉"}
    assert int(playback["query"]["timeout"]) <= 10_000
    assert release["body"] == {"lockId": "lk-test"}
    assert {c["query"]["surface"] for c in fake.calls[1:6] if "surface" in c["query"]} == {"desktop"}


def test_play_without_animation_uses_talking_anim(fake: FakePet) -> None:
    ok, _ = PetClient(BASE).play("就说一句")

    assert ok
    say = next(c for c in fake.calls if c["path"].endswith("/broadcast"))
    assert say["body"] == {"text": "就说一句", "anim": True}
    assert not any(c["path"].endswith("/anim") for c in fake.calls)


def test_play_with_meme_and_duration(fake: FakePet) -> None:
    ok, _ = PetClient(BASE).play("又超了啊", meme="要不直接骂他", duration=8_000)

    assert ok
    say = next(c for c in fake.calls if c["path"].endswith("/broadcast"))
    assert say["body"] == {"text": "又超了啊", "anim": True, "image": "要不直接骂他", "duration": 8000}


def test_play_readback_mismatch_is_failure(fake: FakePet) -> None:
    fake.echo = False
    ok, detail = PetClient(BASE).play("说了但它没记住")

    assert not ok
    assert "读不到" in detail


def test_play_locked_is_failure(fake: FakePet) -> None:
    fake.lock = False
    ok, detail = PetClient(BASE).play("说一句")

    assert not ok
    assert "占用" in detail
    assert not any(c["path"].endswith("/broadcast") for c in fake.calls)


def test_play_offline_still_releases(fake: FakePet) -> None:
    fake.fail_at = 3  # 配置、取锁成功，投喂时断网
    ok, _ = PetClient(BASE).play("说一句")

    assert not ok
    assert fake.paths[-1].endswith("/lock/release")


def test_playback_http_timeout_outlives_long_poll(fake: FakePet) -> None:
    PetClient(BASE).play("说一句", animation="照镜子")

    playback = next(c for c in fake.calls if "/playback/" in c["path"])
    assert playback["timeout"] >= int(playback["query"]["timeout"]) / 1000


def test_play_empty_text_is_rejected(fake: FakePet) -> None:
    ok, _ = PetClient(BASE).play("   ")

    assert not ok
    assert fake.calls == []


# ── 管线集成 ────────────────────────────────────────────────────


def test_pipeline_pet_writes_brief_only(tmp_path: Path, fake: FakePet, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_CHANNELS", "console,pet")
    monkeypatch.setenv("PET_BASE_URL", BASE)
    cfg = Config.load(tmp_path)

    result = run(date="2026-10-28", payload="午饭 35", config=cfg, echo=False)

    assert [r.channel for r in result.renders] == ["console", "pet"]
    assert (result.archive_dir / "pet_task.md").is_file()
    assert fake.calls == []  # 管线只写简报，不碰宠物


def test_pipeline_without_pet_is_offline(tmp_path: Path, fake: FakePet) -> None:
    cfg = Config.load(tmp_path)

    result = run(date="2026-10-28", payload="午饭 35", config=cfg, echo=False)

    assert [r.channel for r in result.renders] == ["console"]
    assert fake.calls == []
    assert not (result.archive_dir / "pet_task.md").exists()

