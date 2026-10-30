"""桌宠渠道：把判断结果交接给宿主 agent，由 agent 决定怎么让它开口。

渲染层不做 AI 推理、也不替 agent 说死台词：本渠道只产出一份《播报简报》
（`archive/YYYY-MM-DD/pet_task.md`），把今天的事实、可用的动画/表情包以及播报命令
交给 agent；真正开口由 agent 调 `scripts/pet_play.py`。

机械部分（surface 匹配 / 取锁 / 长轮询 / 释放 / 读回）收在 `PetClient` 里，
agent 不必自己拼 HTTP——那几个坑（`surface` 必填、`timeout` 上限 10000、
提前放锁会把动画顶掉）都在这里处理掉。

dsh-pet 接口见 https://github.com/PC2005-cloud/dsh-pet（本机前缀 `/dsh-pet-7340`，
只监听 127.0.0.1、无鉴权）。
"""

from __future__ import annotations

import json
import time
from datetime import date as date_type
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..base import BaseChannel
from ...shared.profile import Profile, format_money
from ...shared.types import Judgment, RenderContext, RenderResult

BUBBLE_LIMIT = 60
REQUEST_TIMEOUT = 1.5
LOCK_TTL_MS = 30_000
PLAYBACK_TIMEOUT_MS = 9_000
PLAYBACK_TAIL_SEC = 1.5

#: 进度从低到高，对应 dsh-pet 内置的五段「钱」动画（自定义宠物种类需用 PET_ANIM_TIERS 覆盖）
DEFAULT_TIERS = ("余额-袋空如洗", "余额-数金皱眉", "余额-钱袋如常", "余额-金袋叮当", "余额-钱袋满溢")

#: 每天换一个口吻，避免 agent 落进同一个句式
STYLES = (
    ("具体动作", "给一个明天就能做的具体动作，别讲道理"),
    ("反问", "用一句反问把问题抛回去，别急着给答案"),
    ("自嘲", "拿今天的账开个无害的玩笑，别刻薄"),
    ("比喻", "用一个小比喻说清现在的状态"),
    ("宣布", "像播报一件小事那样宣布，语气轻快"),
    ("关心", "只说一句关心，不给建议"),
    ("吐槽", "吐槽一句，但要让人笑而不是心虚"),
)

_SURFACES = {"web", "desktop", "both"}
_SENTENCE_ENDS = "。！？!?"
_CLIP_ENDS = "，。！？、；：,.!?"
_SKIP_KEYS = {"default", "params", "weight", "noMirror", "id"}


def bubble_text(summary: str) -> str:
    """把总结压成气泡：取第一句，超过 60 字在标点处收口。"""
    text = " ".join((summary or "").split())
    if not text:
        return ""
    sentence = text
    for index, char in enumerate(text):
        if char in _SENTENCE_ENDS:
            sentence = text[: index + 1]
            break
    if len(sentence) <= BUBBLE_LIMIT:
        return sentence
    head = sentence[:BUBBLE_LIMIT]
    cut = max((head.rfind(char) for char in _CLIP_ENDS), default=-1)
    if cut >= BUBBLE_LIMIT // 2:
        head = head[: cut + 1]
    return head.rstrip() + "…"


def tiers_from(raw: str) -> tuple[str, ...]:
    """解析 PET_ANIM_TIERS：空 = 内置五档，`off` = 不播动画，否则要求正好五个名字。"""
    value = (raw or "").strip()
    if value.lower() == "off":
        return ()
    names = tuple(name.strip() for name in value.split(",") if name.strip())
    return names if len(names) == len(DEFAULT_TIERS) else DEFAULT_TIERS


def pick_animation(percent: float | None, tiers: tuple[str, ...]) -> str | None:
    """按目标完成度推荐档位动画；进度未知或无档位时返回 None。"""
    if percent is None or not tiers:
        return None
    ratio = percent * 100
    if ratio >= 100:
        return tiers[-1]
    return tiers[min(max(int(ratio // 25), 0), len(tiers) - 1)]


def is_loopback(base_url: str) -> bool:
    try:
        host = urllib.parse.urlsplit(base_url).hostname
    except ValueError:
        return False
    return bool(host) and host in {"127.0.0.1", "localhost", "::1"}


def _collect_names(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, list):
        for item in value:
            _collect_names(item, out)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in _SKIP_KEYS:
                continue
            _collect_names(item, out)


def style_for(day: str) -> tuple[str, str]:
    """按日期轮换口吻：同一天固定，不同天不同。"""
    try:
        index = date_type.fromisoformat(day).toordinal() % len(STYLES)
    except ValueError:
        index = 0
    return STYLES[index]


def recent_said(archive_dir: Path, limit: int = 3) -> list[str]:
    """读最近几天的 pet_said.md，给 agent 一个「别重复」的参照。"""
    lines: list[str] = []
    for path in sorted(archive_dir.parent.glob("*/pet_said.md"), reverse=True)[:3]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines.extend(row[2:].strip() for row in text.splitlines() if row.startswith("- "))
    return lines[-limit:]


def record_said(archive_dir: Path, text: str, animation: str | None = None) -> None:
    """记一笔今天说过的话，下次简报里就能提醒 agent 别重复。"""
    archive_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"（{animation}）" if animation else ""
    with (archive_dir / "pet_said.md").open("a", encoding="utf-8") as handle:
        handle.write(f"- {text}{suffix}\n")


def _find_entry(payload: dict[str, Any], pet_id: str) -> dict[str, Any] | None:
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        for pet in entry.get("pets") or []:
            if isinstance(pet, dict) and pet.get("id") == pet_id:
                return entry
    return None


def build_brief(
    judgment: Judgment,
    ctx: RenderContext,
    *,
    base_url: str,
    pet_id: str,
    tiers: tuple[str, ...] = DEFAULT_TIERS,
) -> str:
    """给宿主 agent 的播报简报：事实 + 可发挥的空间 + 一条能照抄的命令。"""
    percent = ctx.profile.percent
    progress = "未填写存款" if percent is None else f"{percent * 100:.1f}%"
    savings = format_money(ctx.profile.savings) if ctx.profile.savings is not None else "未填写"
    target = format_money(ctx.profile.target)
    suggested = pick_animation(percent, tiers) or "（这次不推荐档位，随你挑）"
    style_name, style_hint = style_for(ctx.date)
    said = recent_said(ctx.archive_dir)

    lines = [
        f"# 桌宠播报简报 · {ctx.date}",
        "",
        "这条是渲染层交给**宿主 agent** 的活：判断层已经把今天说完，怎么让它开口由你定。",
        "别自己拼 HTTP —— 锁、surface 匹配、长轮询、释放都在脚本里，拼错会静默失败。",
        "",
        "## 今天的事实（可以复述，别改数字）",
        f"- 总结：{judgment.summary}",
        f"- 建议：{judgment.advice}",
        f"- 进度：{progress}（存款 {savings} / 目标 {target}）",
        f"- 素材：{ctx.material_count} 份",
    ]
    if judgment.degraded:
        lines.append("- ⚠️ 降级模式：判断来自本地模板，别说得太笃定")
    lines += [
        "",
        "## 你来定（这才是这一步的价值）",
        f"- **今天的口吻**：{style_name} —— {style_hint}",
        "- **一句话**：≤60 字，说人话。可以安慰、催一句、吐槽、或给一个具体动作；",
        "  不要照抄总结、不要编数字、不要用「先……再……」这种固定句式收尾。",
        "- **一段动画**：`--anim <名字>`；不给就让它用自己的碎碎念动画。",
        "- **配图**：`--meme <名字>`（可选，见 `--list`）。",
        "- **气泡时长**：`--duration <毫秒>`（可选，默认 10000）。",
        "",
        f"按进度，贴切的档位是「{suggested}」；但也可以不按档位，挑更活的一类。",
        "",
        "## 最近说过（重复就没意思了）",
        *([f"- {line}" for line in said] or ["- （还没有历史，今天这句是第一条）"]),
        "",
        "## 播",
        "```bash",
        'python scripts/pet_play.py --text "<你自己写的那句>" --anim "<你挑的动画>"',
        "python scripts/pet_play.py --list    # 这只宠物能播什么、有哪些表情包",
        "```",
        "",
        "> 这里**故意没有示例台词**：照抄示例的结果就是每天同一句话。现写。",
        "",
        f"目标：{base_url} · 宠物：{pet_id}",
        "",
    ]
    return "\n".join(lines)


class PetClient:
    """dsh-pet 的机械层：surface 发现、取锁、投喂、点播、等回执、释放、读回。"""

    def __init__(self, base_url: str, pet_id: str = "main") -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.pet_id = (pet_id or "").strip() or "main"

    # ── 对外 ────────────────────────────────────────────────────

    def catalog(self) -> tuple[list[str], dict[str, str]]:
        """返回（可点播的动画名，表情包 {名字: 适用场景}）。"""
        payload, error = self._request("GET", "/config")
        if error:
            return [], {}
        entry = _find_entry(payload, self.pet_id) or {}
        names: list[str] = []
        _collect_names(entry.get("animations") or {}, names)
        animations = list(dict.fromkeys(n for n in names if n))
        memes = {
            str(key): str(value)
            for key, value in (entry.get("memes") or {}).items()
            if isinstance(key, str)
        }
        return animations, memes

    def play(
        self,
        text: str,
        *,
        animation: str | None = None,
        meme: str | None = None,
        duration: int | None = None,
    ) -> tuple[bool, str]:
        """让宠物说一句（可选配图/动画），成功与否以读回 `/state` 为准。"""
        text = (text or "").strip()
        if not text:
            return False, "文本为空"
        if not self.base_url:
            return False, "未配置 PET_BASE_URL"
        if not is_loopback(self.base_url):
            return False, "PET_BASE_URL 必须是本机地址"

        surface = self.surface()
        if surface is None:
            return False, f"找不到宠物 {self.pet_id} 或它没有显示（/config）"

        lock_id = self._acquire(surface)
        if lock_id is None:
            return False, "取锁失败或被占用（详见下方原因）"

        try:
            ok, detail = self._broadcast(surface, lock_id, text, animation, meme, duration)
            if not ok:
                return False, detail
            if animation:
                self._animate(surface, lock_id, animation)
        finally:
            self._release(surface, lock_id)

        if not self._readback(text):
            return False, "投喂返回 ok，但 /state 里读不到这句话"
        return True, f"已播报：{text}"

    def surface(self) -> str | None:
        """取这只宠物实际所在的面（`display`）；没显示返回 None。"""
        payload, error = self._request("GET", "/config")
        if error:
            return None
        entry = _find_entry(payload, self.pet_id)
        if entry is None:
            return None
        for pet in entry.get("pets") or []:
            if isinstance(pet, dict) and pet.get("id") == self.pet_id:
                display = str(pet.get("display") or "").strip()
                return display if display in _SURFACES else None
        return None

    # ── 协议 ────────────────────────────────────────────────────

    def _acquire(self, surface: str) -> str | None:
        payload, error = self._request(
            "POST", "/lock", params={"pet": self.pet_id, "surface": surface}, body={"ttl": LOCK_TTL_MS}
        )
        if error or not payload.get("ok"):
            return None
        return payload.get("lockId")

    def _broadcast(
        self,
        surface: str,
        lock_id: str,
        text: str,
        animation: str | None,
        meme: str | None,
        duration: int | None,
    ) -> tuple[bool, str]:
        body: dict[str, Any] = {"text": text, "anim": animation is None}
        if meme:
            body["image"] = meme
        if duration is not None:
            body["duration"] = duration
        payload, error = self._request(
            "POST",
            "/broadcast",
            params={"pet": self.pet_id, "surface": surface, "lock": lock_id},
            body=body,
        )
        if error:
            return False, f"投喂失败：{error}"
        if not payload.get("ok"):
            return False, f"投喂被拒（{payload.get('reason')}）"
        return True, ""

    def _animate(self, surface: str, lock_id: str, name: str) -> None:
        payload, error = self._request(
            "POST",
            "/anim",
            params={"pet": self.pet_id, "surface": surface, "lock": lock_id},
            body={"name": name},
        )
        if error or not payload.get("ok"):
            return  # 动画是锦上添花，气泡已经写进去了
        playback_id = payload.get("playbackId")
        if not playback_id:
            return
        payload, error = self._request(
            "GET",
            f"/playback/{urllib.parse.quote(str(playback_id), safe='')}",
            params={"wait": "ended", "timeout": PLAYBACK_TIMEOUT_MS},
            # 长轮询会挂住连接，HTTP 超时必须比它自己等的更久，否则必然先超时
            timeout=PLAYBACK_TIMEOUT_MS / 1000 + 1.0,
        )
        if error:
            return
        if payload.get("status") != "ended":
            time.sleep(PLAYBACK_TAIL_SEC)

    def _release(self, surface: str, lock_id: str) -> None:
        self._request(
            "POST",
            "/lock/release",
            params={"pet": self.pet_id, "surface": surface},
            body={"lockId": lock_id},
        )

    def _readback(self, text: str) -> bool:
        payload, error = self._request("GET", "/state")
        if error:
            return False
        pet = (payload.get("pets") or {}).get(self.pet_id) or {}
        said = ((pet.get("say") or {}).get("data") or {}).get("text")
        return said == text

    # ── HTTP ────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> tuple[dict[str, Any], str | None]:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {}, f"{type(exc).__name__}: {exc}"
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            return {}, "响应不是 JSON"
        return payload if isinstance(payload, dict) else {}, None


class PetChannel(BaseChannel):
    """渲染渠道：产出一份《播报简报》，交给宿主 agent 去播。不发任何网络请求。"""

    name = "pet"

    def __init__(self, base_url: str = "", pet_id: str = "main", tiers: str = "") -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.pet_id = (pet_id or "").strip() or "main"
        self.tiers = tiers_from(tiers)

    def render(self, judgment: Judgment, ctx: RenderContext) -> RenderResult:
        if not self.base_url:
            self._log(ctx.archive_dir, "pet：未配置 PET_BASE_URL，跳过")
            return RenderResult(channel=self.name, output="未配置 PET_BASE_URL，跳过")
        if not is_loopback(self.base_url):
            self._log(ctx.archive_dir, "pet：PET_BASE_URL 不是本机地址，跳过")
            return RenderResult(channel=self.name, output="PET_BASE_URL 必须是本机地址，跳过")
        if ctx.material_count == 0:
            self._log(ctx.archive_dir, "pet：今天没有素材，跳过播报")
            return RenderResult(channel=self.name, output="今天没有素材，跳过播报")

        brief = build_brief(judgment, ctx, base_url=self.base_url, pet_id=self.pet_id, tiers=self.tiers)
        ctx.archive_dir.mkdir(parents=True, exist_ok=True)
        path = ctx.archive_dir / "pet_task.md"
        path.write_text(brief, encoding="utf-8")
        if ctx.echo:
            print(f"桌宠简报：{path}（读它，用 scripts/pet_play.py 播报）")
        return RenderResult(channel=self.name, output=brief, artifacts=[path])

    @staticmethod
    def _log(archive_dir: Path, message: str) -> None:
        archive_dir.mkdir(parents=True, exist_ok=True)
        with (archive_dir / "render.log").open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")


def suggest_animation(profile: Profile, tiers: tuple[str, ...] = DEFAULT_TIERS) -> str | None:
    """给 `--auto` 用：按档案进度推荐一段动画。"""
    return pick_animation(profile.percent, tiers)


__all__ = [
    "BUBBLE_LIMIT",
    "DEFAULT_TIERS",
    "PetChannel",
    "PetClient",
    "bubble_text",
    "build_brief",
    "is_loopback",
    "pick_animation",
    "record_said",
    "recent_said",
    "style_for",
    "suggest_animation",
    "tiers_from",
]
