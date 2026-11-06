"""每日插画：指南截断、prompt 解析、报表拦截、参考图回退、落盘与降级。"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
from dataclasses import replace
from pathlib import Path

import pytest

from step_ledger.pipeline import run as pipeline_run
from step_ledger.render import illustration
from step_ledger.render.channels.pet import LocalImageServer
from step_ledger.render.illustration import (
    IllustrationError,
    build_context,
    load_existing,
    load_guide,
    looks_like_report,
    parse_prompt_plan,
    reference_image,
    run,
)
from step_ledger.shared.config import Config
from step_ledger.shared.types import Illustration, Judgment, RenderContext

DATE = "2026-11-06"
GUIDE = "# 指南\n\n只写一个瞬间。\n\n---\n\n## 附录：调用方看这里\n"


class FakeProvider:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(self, system: str, user: str, *, temperature: float = 0.8):
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return (
            json.dumps(
                {
                    "lens": "moment",
                    "moment": "夜里看到小票，眉毛垮下来",
                    "prompt": "深夜书桌前，鲸鱼娘捏着一张小票，小票上只有一个数字 81，暖黄台灯。",
                },
                ensure_ascii=False,
            ),
            {"total_tokens": 12},
        )


def _cfg(tmp_path: Path, *, with_key: bool = True, reference: Path | None = None) -> Config:
    cfg = Config.load(tmp_path)
    return replace(
        cfg,
        provider="openai",
        api_key="fake-judge-key",
        channels=("console", "pet"),
        pet_base_url="",
        illustration_enabled="auto",
        illustration_api_key="fake-image-key" if with_key else "",
        illustration_reference=str(reference or ""),
        illustration_character="",
    )


def _judgment() -> Judgment:
    return Judgment(summary="今天花得有点多。", advice="明天收着点。", runtime={"material_count": 1})


def _ctx(tmp_path: Path) -> RenderContext:
    return RenderContext(out_dir=tmp_path / "archive" / DATE, echo=False)


def _write_guide(root: Path) -> None:
    path = root / "docs" / "prompt-pet-illustration.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(GUIDE, encoding="utf-8")


# ── 指南 / prompt ───────────────────────────────────────────────


def test_load_guide_strips_appendix(tmp_path: Path) -> None:
    _write_guide(tmp_path)

    guide = load_guide(tmp_path)

    assert "只写一个瞬间" in guide
    assert "附录" not in guide


def test_load_guide_missing_is_error(tmp_path: Path) -> None:
    with pytest.raises(IllustrationError):
        load_guide(tmp_path)


def test_parse_prompt_plan_accepts_fenced_json() -> None:
    content = '```json\n{"lens":"texture","moment":"空白账本","prompt":"俯视账本，留白。"}\n```'
    plan = parse_prompt_plan(content)

    assert plan.lens == "texture"
    assert plan.moment == "空白账本"
    assert plan.prompt == "俯视账本，留白。"


def test_parse_prompt_plan_rejects_empty_prompt() -> None:
    with pytest.raises(IllustrationError):
        parse_prompt_plan('{"lens":"moment","prompt":""}')


def test_looks_like_report_allows_one_number() -> None:
    assert looks_like_report("深夜书桌，小票上只有一个数字 81，旁边一枚硬币。") is None
    assert looks_like_report("Q版约 3 头身，小票上只有一个数字 81。") is None


def test_looks_like_report_rejects_amount_list() -> None:
    assert looks_like_report("小票上写着 29、49、81 三行明细。") is not None
    assert looks_like_report("账户尾号 1234 的卡。") is not None
    assert looks_like_report("画面里有一张 https://example.com 的图。") is not None


# ── 参考图 ──────────────────────────────────────────────────────


def test_reference_falls_back_to_local(tmp_path: Path) -> None:
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    cfg = _cfg(tmp_path, reference=ref)

    data, source, reason = reference_image(cfg)

    assert data is not None
    assert data.startswith(b"\x89PNG")
    assert source == "local"
    assert reason == ""


def test_reference_missing_is_skipped(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, reference=tmp_path / "nope.png")

    data, source, reason = reference_image(cfg)

    assert data is None
    assert source == "none"
    assert "不存在" in reason


# ── 生图落盘 / 降级 ─────────────────────────────────────────────


def test_run_writes_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_guide(tmp_path)
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    cfg = _cfg(tmp_path, reference=ref)

    monkeypatch.setattr(illustration, "OpenAICompatibleProvider", FakeProvider)
    monkeypatch.setattr(
        illustration,
        "generate_image",
        lambda cfg, prompt, reference: (
            b"\xff\xd8\xff" + b"fake-jpeg",
            {"model": "fake-model", "size": "1536x2048", "usage": {"total_tokens": 123}},
        ),
    )

    result = run(cfg, _judgment(), _ctx(tmp_path))

    assert result.image is not None
    assert result.image.name == "illustration.jpg"
    assert result.image.read_bytes().startswith(b"\xff\xd8\xff")
    assert result.lens == "moment"
    assert "81" in result.prompt

    out = tmp_path / "archive" / DATE
    meta = json.loads((out / "illustration.json").read_text(encoding="utf-8"))
    assert meta["reference"] == "local"
    assert meta["model"] == "fake-model"
    assert meta["text_usage"] == {"total_tokens": 12}
    prompt_text = (out / "illustration_prompt.md").read_text(encoding="utf-8")
    assert "小票上只有一个数字 81" in prompt_text
    assert "附录" not in prompt_text

    # 同一路径的图会被重跑覆盖，所以另存一份带时间戳的副本供查看
    stamps = sorted(out.glob("illustration-[0-9][0-9][0-9][0-9].jpg"))
    assert len(stamps) == 1
    assert stamps[0].read_bytes() == result.image.read_bytes()


def test_run_without_key_skips(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, with_key=False)
    result = run(cfg, _judgment(), _ctx(tmp_path))

    assert result.image is None
    assert "ILLUSTRATION_API_KEY" in result.reason


def test_run_skips_degraded(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    judgment = _judgment()
    judgment.degraded = True

    result = run(cfg, judgment, _ctx(tmp_path))

    assert result.image is None
    assert "降级" in result.reason


def test_run_does_not_call_network_without_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def explode(*args: object, **kwargs: object):
        calls.append("called")
        raise urllib.error.URLError("should not call")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    cfg = _cfg(tmp_path, with_key=False)

    result = run(cfg, _judgment(), _ctx(tmp_path))

    assert result.image is None
    assert calls == []


# ── 已有产物 / 本地图服务 ──────────────────────────────────────


def test_load_existing_and_stale(tmp_path: Path) -> None:
    archive = tmp_path / "archive" / DATE
    archive.mkdir(parents=True)
    (archive / "illustration.jpg").write_bytes(b"\xff\xd8\xff")
    (archive / "illustration.json").write_text(
        json.dumps({"image": "illustration.jpg", "lens": "moment", "moment": "x", "prompt": "y"}),
        encoding="utf-8",
    )

    fresh = load_existing(archive)
    stale = load_existing(archive, stale=True)

    assert fresh is not None and fresh.image is not None
    assert stale is not None and stale.image is None
    assert "过期" in stale.reason


def test_local_image_server_serves_one_file(tmp_path: Path) -> None:
    path = tmp_path / "illustration.png"
    payload = b"\x89PNG\r\n\x1a\nhello"
    path.write_bytes(payload)

    with LocalImageServer(path) as server:
        parts = urllib.parse.urlsplit(server.url)
        connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=2)
        connection.request("GET", parts.path)
        response = connection.getresponse()
        body = response.read()
        connection.close()

        assert response.status == 200
        assert response.getheader("Content-Type") == "image/png"
        assert body == payload
        assert server.wait(1.0)


def test_pipeline_reuses_existing_when_generation_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RENDER_CHANNELS", "console,pet")
    monkeypatch.setenv("PET_BASE_URL", "http://127.0.0.1:9/dsh-pet-7340")
    # 先放一张当天已生成的图
    archive = tmp_path / "archive" / "2026-10-28"
    archive.mkdir(parents=True)
    (archive / "illustration.jpg").write_bytes(b"\xff\xd8\xff-old")
    (archive / "illustration.json").write_text(
        json.dumps(
            {
                "image": "illustration.jpg",
                "lens": "moment",
                "moment": "旧图这一幕",
                "prompt": "旧图 prompt",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # 本次生成失败，但当天已有图不该被丢掉
    monkeypatch.setattr(
        "step_ledger.pipeline.illustration.run",
        lambda cfg, judgment, ctx: Illustration(reason="本次生成跳过"),
    )

    cfg = Config.load(tmp_path)
    result = pipeline_run(date="2026-10-28", payload="午饭 35", config=cfg, echo=False)

    assert result.illustration is not None
    assert result.illustration.image == archive / "illustration.jpg"
    assert "沿用当天已有图" in result.illustration.reason
    assert "--image" in (archive / "pet_task.md").read_text(encoding="utf-8")
