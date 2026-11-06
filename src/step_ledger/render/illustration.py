"""每日插画：文本模型写 prompt → 图像模型出图。

这是渲染阶段的第一步（`judge` 之后、渠道之前），不是渠道：
它可能花钱、可能失败，所以所有问题都收敛成 `Illustration(reason=...)`，
绝不把异常抛给管线。渠道仍然只读成品、不发网络请求。
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..judge.providers.openai_compatible import OpenAICompatibleProvider
from ..shared.config import Config
from ..shared.types import Illustration, Judgment, RenderContext

GUIDE_RELATIVE = Path("docs") / "prompt-pet-illustration.md"
GUIDE_SEPARATOR = "\n---\n"
TEXT_TIMEOUT = 60.0
IMAGE_TIMEOUT = 120.0
MAX_PROMPT_CHARS = 800
MAX_MOMENT_CHARS = 40


class IllustrationError(RuntimeError):
    """插画这一步可以预期的失败：跳过，不影响归档。"""


@dataclass
class PromptPlan:
    lens: str
    moment: str
    prompt: str
    text_usage: dict[str, Any] = field(default_factory=dict)


def load_guide(root: Path) -> str:
    """读 prompt 指南里 `---` 之前的部分；附录 A 是给调用方的，不进 system prompt。"""
    path = root / GUIDE_RELATIVE
    if not path.is_file():
        raise IllustrationError(f"找不到 prompt 指南：{path}")
    text = path.read_text(encoding="utf-8")
    head = text.split(GUIDE_SEPARATOR, 1)[0].strip()
    if not head:
        raise IllustrationError(f"prompt 指南为空：{path}")
    return head


def parse_prompt_plan(content: str) -> PromptPlan:
    """解析模型输出；允许 Markdown 围栏，其余一律要求是合法 JSON。"""
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise IllustrationError(f"模型输出不是 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise IllustrationError("模型输出不是 JSON 对象")

    lens = str(data.get("lens") or "moment").strip().lower()
    if lens not in {"moment", "texture", "slow"}:
        lens = "moment"
    moment = " ".join(str(data.get("moment") or "").split())[:MAX_MOMENT_CHARS]
    prompt = " ".join(str(data.get("prompt") or "").split())
    if not prompt:
        raise IllustrationError("模型输出 prompt 为空")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise IllustrationError(f"prompt 超过 {MAX_PROMPT_CHARS} 字")
    if not moment:
        moment = prompt[:MAX_MOMENT_CHARS]
    return PromptPlan(lens=lens, moment=moment, prompt=prompt)


_LIST_HINTS = ("合计", "明细", "总计", "清单", "表格", "账单列表")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def looks_like_report(prompt: str) -> str | None:
    """机械拦“报表”：明细字样、多个数字、账户尾号、URL。返回原因或 None。"""
    if any(hint in prompt for hint in _LIST_HINTS):
        return "出现明细/表格字样"
    if re.search(r"(尾号|账号|卡号)\s*[：:]?\s*\d{3,}", prompt):
        return "出现账户尾号"
    if re.search(r"https?://", prompt):
        return "出现 URL"
    numbers: list[str] = []
    for match in _NUMBER.finditer(prompt):
        tail = prompt[match.end() : match.end() + 3].lstrip()
        if tail.startswith("头身"):
            continue  # 角色比例不是金额
        numbers.append(match.group())
    if len(numbers) > 1:
        return "出现多个数字"
    return None


def facts_payload(judgment: Judgment) -> dict[str, Any] | None:
    """只给算好的事实，不给原材料（尤其不给余额摘录）。"""
    facts = judgment.facts
    if facts is None:
        return None
    return {
        "date": facts.date,
        "goal": asdict(facts.goal),
        "month": None if facts.month is None else asdict(facts.month),
        "pace": None if facts.pace is None else asdict(facts.pace),
    }


def recent_illustrations(archive_root: Path, limit: int = 3) -> list[dict[str, str]]:
    """最近几天的镜头与瞬间，用来避免每天画同一件事。"""
    out: list[dict[str, str]] = []
    for path in sorted(archive_root.glob("*/illustration.json"), reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"lens": str(data.get("lens") or ""), "moment": str(data.get("moment") or "")})
    return out


def build_context(judgment: Judgment, ctx: RenderContext, character: str = "") -> dict[str, Any]:
    context: dict[str, Any] = {
        "date": judgment.facts.date if judgment.facts is not None else "",
        "facts": facts_payload(judgment),
        "trend": judgment.trend.to_dict(),
        "summary": judgment.summary,
        "advice": judgment.advice,
        "material_count": judgment.runtime.get("material_count", 0),
        "recent_said": ctx.recent_said[-3:],
        "recent_illustrations": recent_illustrations(ctx.out_dir.parent, 3),
    }
    if character.strip():
        context["character"] = character.strip()
    return context


def request_prompt(
    provider: OpenAICompatibleProvider,
    guide: str,
    context: dict[str, Any],
) -> PromptPlan:
    """一次生成 + 一次纠错；再坏就交给上层跳过。"""
    user = json.dumps(context, ensure_ascii=False, indent=2)
    content, usage = provider.complete(guide, user, temperature=0.8)
    try:
        plan = parse_prompt_plan(content)
        problem = looks_like_report(plan.prompt)
        if problem is None:
            return PromptPlan(plan.lens, plan.moment, plan.prompt, usage)
    except IllustrationError as exc:
        problem = str(exc)

    nudge = (
        f"上一次输出有问题：{problem}。只输出 JSON；一个瞬间；最多一个关键数字 + 一句短句；"
        "不要明细、表格、多行金额、账户尾号或 URL。"
    )
    content, usage = provider.complete(guide + "\n\n" + nudge, user, temperature=0.8)
    plan = parse_prompt_plan(content)
    problem = looks_like_report(plan.prompt)
    if problem is not None:
        raise IllustrationError(problem)
    return PromptPlan(plan.lens, plan.moment, plan.prompt, usage)


# ── 参考图 ──────────────────────────────────────────────────────


def _is_loopback(base_url: str) -> bool:
    try:
        host = urllib.parse.urlsplit(base_url).hostname
    except ValueError:
        return False
    return bool(host) and host in {"127.0.0.1", "localhost", "::1"}


def _request_bytes(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _request_json(
    url: str,
    timeout: float,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IllustrationError(f"请求失败：{exc}") from exc
    try:
        payload = json.loads(raw or "{}")
    except ValueError as exc:
        raise IllustrationError("响应不是 JSON") from exc
    if not isinstance(payload, dict):
        raise IllustrationError("响应不是 JSON 对象")
    return payload


def find_character_root(base_url: str, pet_id: str) -> str | None:
    payload = _request_json(base_url.rstrip("/") + "/config", 3.0)
    for root, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        for pet in entry.get("pets") or []:
            if isinstance(pet, dict) and pet.get("id") == pet_id:
                return str(root)
    return None


def _mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def reference_image(cfg: Config) -> tuple[bytes | None, str, str]:
    """优先 dsh-pet 的 /character，其次本地参考图；都没有就不画。"""
    if cfg.pet_base_url and _is_loopback(cfg.pet_base_url):
        root = cfg.pet_character_root.strip()
        if not root:
            try:
                root = find_character_root(cfg.pet_base_url, cfg.pet_id) or ""
            except IllustrationError:
                root = ""
        if root:
            query = urllib.parse.urlencode({"root": root})
            try:
                data = _request_bytes(
                    f"{cfg.pet_base_url.rstrip('/')}/character?{query}", 10.0
                )
            except (urllib.error.URLError, TimeoutError, OSError):
                data = b""
            if data:
                return data, "character", ""

    if cfg.illustration_reference:
        path = Path(cfg.illustration_reference).expanduser()
        if not path.is_absolute():
            path = cfg.root / path
        if path.is_file():
            return path.read_bytes(), "local", ""
        return None, "none", f"本地参考图不存在：{path}"

    return None, "none", "没有可用的角色参考图（/character 不可用且没配 ILLUSTRATION_REFERENCE）"


# ── 生图 ────────────────────────────────────────────────────────


def generate_image(
    cfg: Config,
    prompt: str,
    reference: bytes | None,
) -> tuple[bytes, dict[str, Any]]:
    body: dict[str, Any] = {
        "model": cfg.illustration_model,
        "prompt": prompt,
        "size": cfg.illustration_size,
        "response_format": "url",
        "watermark": False,
    }
    if reference:
        body["image"] = [f"data:{_mime(reference)};base64,{base64.b64encode(reference).decode()}"]
    payload = _request_json(
        cfg.illustration_base_url.rstrip("/") + "/images/generations",
        IMAGE_TIMEOUT,
        method="POST",
        body=body,
        headers={"Authorization": f"Bearer {cfg.illustration_api_key}"},
    )
    items = payload.get("data") or []
    item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
    if item.get("url"):
        try:
            image = _request_bytes(str(item["url"]), IMAGE_TIMEOUT)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise IllustrationError(f"下载生成图失败：{exc}") from exc
    elif item.get("b64_json"):
        try:
            image = base64.b64decode(str(item["b64_json"]))
        except (ValueError, TypeError) as exc:
            raise IllustrationError(f"生图返回的 b64 无法解码：{exc}") from exc
    else:
        raise IllustrationError("生图返回里没有 url / b64_json")
    if not image:
        raise IllustrationError("生图返回空图片")
    return image, {
        "model": payload.get("model") or cfg.illustration_model,
        "size": item.get("size") or cfg.illustration_size,
        "usage": payload.get("usage") or {},
    }


def _save_image(out_dir: Path, data: bytes) -> Path:
    suffix = ".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
    path = out_dir / f"illustration{suffix}"
    for old in (out_dir / "illustration.jpg", out_dir / "illustration.png"):
        if old.exists() and old != path:
            old.unlink()
    path.write_bytes(data)
    return path


def _write_prompt(out_dir: Path, context: dict[str, Any], plan: PromptPlan) -> None:
    text = "\n".join(
        [
            "# 插画 Prompt",
            "",
            f"- lens：{plan.lens}",
            f"- moment：{plan.moment}",
            "",
            "## 上下文",
            "```json",
            json.dumps(context, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Prompt",
            plan.prompt,
            "",
        ]
    )
    (out_dir / "illustration_prompt.md").write_text(text, encoding="utf-8")


def _write_meta(
    out_dir: Path,
    *,
    plan: PromptPlan,
    image_path: Path,
    reference: str,
    image_meta: dict[str, Any],
    elapsed_ms: int,
) -> None:
    meta = {
        "date": out_dir.name,
        "lens": plan.lens,
        "moment": plan.moment,
        "prompt": plan.prompt,
        "image": image_path.name,
        "model": image_meta.get("model", ""),
        "size": image_meta.get("size", ""),
        "reference": reference,
        "usage": image_meta.get("usage") or {},
        "text_usage": plan.text_usage,
        "elapsed_ms": elapsed_ms,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (out_dir / "illustration.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _log(out_dir: Path, message: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "render.log").open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def skip_reason(cfg: Config, judgment: Judgment) -> str:
    if cfg.illustration_enabled in {"off", "0", "false", "no"}:
        return "ILLUSTRATION_ENABLED=off"
    if not cfg.illustration_api_key:
        return "没配 ILLUSTRATION_API_KEY"
    if "pet" not in cfg.channels:
        return "RENDER_CHANNELS 里没有 pet"
    if cfg.provider in {"stub", "offline", "none"} or not cfg.api_key:
        return "文本模型不可用（JUDGE_PROVIDER=stub 或没 key）"
    if judgment.degraded:
        return "判断降级"
    if judgment.runtime.get("material_count", 0) == 0:
        return "当天没有素材"
    if not cfg.pet_base_url and not cfg.illustration_reference:
        return "没有参考图来源（PET_BASE_URL 与 ILLUSTRATION_REFERENCE 都空）"
    return ""


def run(cfg: Config, judgment: Judgment, ctx: RenderContext) -> Illustration:
    """生成今天的插画；任何失败都返回带 reason 的 Illustration，不抛异常。"""
    reason = skip_reason(cfg, judgment)
    if reason:
        return Illustration(reason=reason)

    started = time.monotonic()
    try:
        guide = load_guide(cfg.root)
        provider = OpenAICompatibleProvider(cfg.api_key, cfg.model, cfg.base_url)
        context = build_context(judgment, ctx, cfg.illustration_character)
        plan = request_prompt(provider, guide, context)
        reference, source, reference_reason = reference_image(cfg)
        if reference is None:
            raise IllustrationError(reference_reason)
        image, image_meta = generate_image(cfg, plan.prompt, reference)
        ctx.out_dir.mkdir(parents=True, exist_ok=True)
        image_path = _save_image(ctx.out_dir, image)
        _write_prompt(ctx.out_dir, context, plan)
        _write_meta(
            ctx.out_dir,
            plan=plan,
            image_path=image_path,
            reference=source,
            image_meta=image_meta,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        return Illustration(image=image_path, prompt=plan.prompt, moment=plan.moment, lens=plan.lens)
    except Exception as exc:  # 插画失败绝不拖垮归档
        message = f"插画跳过：{exc}"
        _log(ctx.out_dir, message)
        return Illustration(reason=str(exc))


def load_existing(archive_dir: Path, *, stale: bool = False) -> Illustration | None:
    """`--stage render` 用：只读已生成的图，不调模型。"""
    path = archive_dir / "illustration.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Illustration(reason="illustration.json 读不出来")
    if stale:
        return Illustration(reason="判断已重算，旧图可能过期；跑 --stage illustrate 补图")
    image_name = str(data.get("image") or "")
    image = archive_dir / image_name if image_name else None
    if image is None or not image.is_file():
        return Illustration(reason="插画文件缺失")
    return Illustration(
        image=image,
        prompt=str(data.get("prompt") or ""),
        moment=str(data.get("moment") or ""),
        lens=str(data.get("lens") or "moment"),
    )


__all__ = [
    "GUIDE_RELATIVE",
    "IllustrationError",
    "PromptPlan",
    "build_context",
    "facts_payload",
    "find_character_root",
    "generate_image",
    "load_existing",
    "load_guide",
    "looks_like_report",
    "parse_prompt_plan",
    "recent_illustrations",
    "reference_image",
    "request_prompt",
    "run",
    "skip_reason",
]
