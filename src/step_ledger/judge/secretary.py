"""秘书：先观察，再算账，再翻旧账，最后说话。

顺序不能换——说话要用到算好的数字，所以事实必须排在说话前面。这也是为什么
判断层每天有两次模型调用：一次只读余额，一次只写字。

每一步各自失败、各自降级，不互相牵连：

- 观察失败 → 没有今天的余额，事实退回「上一个有余额的日子」，报告标「截至 X」
- 说话失败 → 用 stub 的话，但事实仍然是权威的（降级路径第一次也有数字）
"""

from __future__ import annotations

from pathlib import Path

from .base import BaseProvider, ProviderError
from .facts import compute, summarize_trend
from .history import History
from .observe import verify
from .prompt import build_prompt, read_materials
from .providers.stub import StubProvider
from ..shared.profile import Profile
from ..shared.types import Judgment, Observation

#: `runtime` 只装「这次运行发生了什么」，白名单之外的键一律丢掉
RUNTIME_KEYS = (
    "provider",
    "model",
    "usage",
    "material_count",
    "skipped",
    "degraded_reason",
    "requested_provider",
    "profile_created",
    "steps",
)


def run(
    *,
    materials_dir: Path,
    profile: Profile,
    date: str,
    provider: BaseProvider,
    history: History,
    requested: str = "",
    profile_created: bool = False,
    backfilled: bool = False,
    provider_error: str | None = None,
) -> Judgment:
    """跑完判断层的一天：观测 → 事实 → 趋势 → 说话。"""
    text, skipped = read_materials(materials_dir)
    files = _material_files(materials_dir)
    runtime: dict = {
        "material_count": len(files),
        "skipped": skipped,
        "steps": {},
        "profile_created": profile_created,
    }
    degraded = False
    notes: list[str] = []
    if provider_error:
        degraded = True
        notes.append(provider_error)

    observation: Observation
    if not files:
        # 0 份素材不问模型：空料只会让它编
        observation = Observation()
        runtime["steps"]["observe"] = "skipped"
    else:
        try:
            observation = verify(provider.observe(text, date), text, date)
            # 「跑通了但没读到数」和「失败了」不是一回事，分开记
            runtime["steps"]["observe"] = "ok" if observation.balance.value is not None else "empty"
        except Exception as exc:  # 观察挂了不拖垮说话：事实退回历史余额
            observation = Observation()
            runtime["steps"]["observe"] = "failed"
            degraded = True
            notes.append(f"观察失败：{exc}")

    facts = compute(
        day=date,
        profile=profile,
        observation=observation,
        history=history,
        backfilled=backfilled,
    )
    trend = summarize_trend(day=date, history=history, facts=facts)

    if not files:
        judgment = StubProvider().speak(materials_dir, profile, date, facts, trend)
        runtime["steps"]["speak"] = "stub"
        runtime["provider"] = "none"
    else:
        try:
            judgment = provider.speak(materials_dir, profile, date, facts, trend)
            if not judgment.is_valid:
                raise ProviderError("判断结果为空")
            runtime["steps"]["speak"] = "ok"
        except Exception as exc:  # 模型不可用 → 模板兜底，但必须标注降级
            judgment = StubProvider().speak(materials_dir, profile, date, facts, trend)
            runtime["steps"]["speak"] = "failed"
            degraded = True
            notes.append(f"说话失败：{exc}")

    if not judgment.prompt:
        judgment.prompt = build_prompt(profile, text, date, len(files), facts, trend)

    merged = {key: value for key, value in {**judgment.runtime, **runtime}.items() if key in RUNTIME_KEYS}
    merged["steps"] = runtime["steps"]
    if requested:
        merged["requested_provider"] = requested
    if notes:
        merged["degraded_reason"] = "；".join(notes)

    judgment.facts = facts
    judgment.trend = trend
    judgment.observation = observation
    judgment.runtime = merged
    judgment.degraded = degraded or judgment.degraded
    return judgment


def backfill(*, judgment: Judgment, profile: Profile, date: str, history: History) -> Judgment:
    """只补事实，不动已经写过的话。

    旧归档没有事实快照、而素材又已经被清理时，唯一正确的做法是：把数字补上，
    保留当初模型写的 summary/advice，并标记 `facts_backfilled`。此时「数字和话同源」
    已经不成立，所以必须留痕，不能假装是同一轮算出来的。
    """
    facts = compute(
        day=date,
        profile=profile,
        observation=Observation(),
        history=history,
        backfilled=True,
    )
    judgment.facts = facts
    judgment.trend = summarize_trend(day=date, history=history, facts=facts)
    judgment.runtime = {**judgment.runtime, "facts_backfilled": True}
    return judgment


def _material_files(materials_dir: Path) -> list[Path]:
    if not materials_dir.is_dir():
        return []
    return sorted(
        path for path in materials_dir.iterdir() if path.is_file() and path.name != "profile.md"
    )


__all__ = ["RUNTIME_KEYS", "run"]
