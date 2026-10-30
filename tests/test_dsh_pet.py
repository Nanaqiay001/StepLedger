import json
import urllib.error
from io import BytesIO
from pathlib import Path

from step_ledger.pipeline import run
from step_ledger.render.channels.dsh_pet import (
    DshPetChannel,
    build_dsh_prompt,
    post_to_dsh_bridge,
)
from step_ledger.shared.config import Config
from step_ledger.shared.profile import Profile
from step_ledger.shared.types import Judgment, RenderContext


class DummyResponse:
    def __init__(self, status: int = 200, body: bytes = b'{"ok": true}'):
        self.status = status
        self.body = body

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


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
    assert "若当前环境或工具不支持所给 mood 参数则可忽略" in prompt


def test_post_to_dsh_bridge_missing_token():
    success, detail = post_to_dsh_bridge("test prompt", bridge_token="")
    assert success is False
    assert "未配置 DSH_BRIDGE_TOKEN" in detail


def test_post_to_dsh_bridge_success(monkeypatch):
    captured = {}

    def mock_urlopen(req, timeout=10.0):
        captured["url"] = req.full_url
        captured["token"] = req.headers.get("X-bridge-token") or req.headers.get("x-bridge-token")
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return DummyResponse(200, b'{"status": "ok"}')

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    success, detail = post_to_dsh_bridge(
        "复盘测试内容",
        bridge_url="http://127.0.0.1:8000/api/ai-bridge/post",
        bridge_token="secret-token-123",
    )

    assert success is True
    assert "成功" in detail
    assert captured["url"] == "http://127.0.0.1:8000/api/ai-bridge/post"
    assert captured["token"] == "secret-token-123"
    assert captured["body"]["from"] == "step-ledger"
    assert captured["body"]["text"] == "复盘测试内容"


def test_post_to_dsh_bridge_http_error(monkeypatch):
    def mock_urlopen(req, timeout=10.0):
        raise urllib.error.HTTPError(req.full_url, 500, "Internal Error", {}, BytesIO(b""))

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    success, detail = post_to_dsh_bridge(
        "复盘测试内容",
        bridge_url="http://127.0.0.1:8000/api/ai-bridge/post",
        bridge_token="secret-token-123",
    )

    assert success is False
    assert "500" in detail


def test_dsh_pet_channel_render_without_bridge(tmp_path):
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


def test_pipeline_with_dsh_pet_channel_bridge_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER_CHANNELS", "console,dsh-pet")
    monkeypatch.setenv("DSH_BRIDGE_TOKEN", "fake-token")
    monkeypatch.setenv("DSH_BRIDGE_URL", "http://127.0.0.1:9999/api/ai-bridge/post")
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)
    cfg = Config.load(tmp_path)

    # 试图向未开启的本地端口 POST 时网络连接拒绝，管线应捕获此异常而不挂掉
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
