"""管线编排：采集 → 判断 → 渲染。两个入口（agent / cron）都走这里。

每一层都可以单独重跑（`--stage`），同日重复执行覆盖当天产物，不新建日期目录。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_type
from pathlib import Path

from .collect.adapters.folder import FolderAdapter
from .collect.adapters.manual import ManualAdapter, material_files
from .judge.base import ProviderError
from .judge.prompt import build_prompt, read_materials
from .judge.providers.openai_compatible import OpenAICompatibleProvider
from .judge.providers.stub import StubProvider
from .render.channels.console import ConsoleChannel
from .shared.config import Config
from .shared.profile import Profile, ensure_profile, load_profile
from .shared.types import (
    CollectResult,
    Judgment,
    PipelineResult,
    RenderContext,
    RenderResult,
)


def run(
    *,
    date: str | None = None,
    payload: str | Path | None = None,
    root: Path | str | None = None,
    stage: str = "all",
    provider: str | None = None,
    sources: list[str | Path] | None = None,
    echo: bool = True,
    config: Config | None = None,
) -> PipelineResult:
    cfg = config or Config.load(root)
    run_date = date or date_type.today().isoformat()
    materials_dir = cfg.materials_for(run_date)
    archive_dir = cfg.archive_for(run_date)
    result = PipelineResult(date=run_date, materials_dir=materials_dir, archive_dir=archive_dir, stage=stage)

    if stage in ("all", "collect"):
        collected = _collect(cfg, run_date, materials_dir, payload, sources)
        result.skipped.extend(collected.skipped)
    else:
        collected = CollectResult(materials_dir=materials_dir)
        collected.files = material_files(materials_dir)

    profile = _load_or_create_profile(cfg.profile_path, create=stage in ("all", "judge"))

    if stage in ("all", "judge"):
        result.judgment = _judge(cfg, materials_dir, profile, run_date, provider)
        result.skipped.extend(result.judgment.meta.get("skipped") or [])
        _write_judgment(result.judgment, archive_dir)

    if stage in ("all", "render"):
        if result.judgment is None:
            result.judgment = _read_judgment(archive_dir)
        # 档案可能刚改过：重跑渲染时也要刷新当天的进度快照
        _stamp_progress(result.judgment, profile, run_date)
        if stage == "render":
            _write_judgment(result.judgment, archive_dir)
        ctx = RenderContext(
            date=run_date,
            archive_dir=archive_dir,
            profile=profile,
            material_count=len(collected.files),
            profile_created=profile.created,
            echo=echo,
        )
        result.renders = _render(cfg, result.judgment, ctx)

    return result


def _load_or_create_profile(path: Path, *, create: bool) -> Profile:
    if create:
        return ensure_profile(path)
    return load_profile(path)


def _collect(
    cfg: Config,
    run_date: str,
    materials_dir: Path,
    payload: str | Path | None,
    sources: list[str | Path] | None,
) -> CollectResult:
    """手动投递 + 自动素材夹，都落进当天同一个素材目录。"""
    merged = ManualAdapter().collect(materials_dir, payload)
    source_dirs = sources if sources else cfg.source_dirs
    for source in source_dirs:
        extra = FolderAdapter(run_date).collect(materials_dir, source)
        merged.added.extend(extra.added)
        merged.skipped.extend(extra.skipped)
    merged.files = material_files(materials_dir)
    return merged


def _judge(cfg: Config, materials_dir: Path, profile: Profile, run_date: str, override: str | None) -> Judgment:
    requested = (override or cfg.provider or "stub").strip().lower()
    try:
        provider = _build_provider(cfg, requested)
        judgment = provider.judge(materials_dir, profile, run_date)
        if not judgment.is_valid:
            raise ProviderError("判断结果为空")
    except Exception as exc:  # 模型不可用 → 用模板兜底，但必须标注降级
        judgment = StubProvider().judge(materials_dir, profile, run_date)
        judgment.degraded = True
        judgment.meta["degraded_reason"] = str(exc)
        judgment.meta["requested_provider"] = requested

    if not judgment.prompt:
        text, _ = read_materials(materials_dir)
        judgment.prompt = build_prompt(profile, text, run_date, len(material_files(materials_dir)))

    _stamp_progress(judgment, profile, run_date)
    return judgment


def _stamp_progress(judgment: Judgment, profile: Profile, run_date: str) -> None:
    judgment.meta["date"] = run_date
    judgment.meta["progress"] = {
        "target": profile.target,
        "savings": profile.savings,
        "distance": profile.distance,
        "percent": profile.percent,
    }


def _build_provider(cfg: Config, name: str):
    if name in ("stub", "offline", "none"):
        return StubProvider()
    if name in ("openai", "openai_compatible", "compatible"):
        return OpenAICompatibleProvider(cfg.api_key, cfg.model, cfg.base_url)
    raise ProviderError(f"未知的 JUDGE_PROVIDER：{name}")


def _render(cfg: Config, judgment: Judgment, ctx: RenderContext) -> list[RenderResult]:
    renders: list[RenderResult] = []
    for name in cfg.channels:
        channel = {"console": ConsoleChannel}.get(name)
        if channel is None:
            _log(ctx.archive_dir, f"未知渠道，已跳过：{name}")
            continue
        try:
            renders.append(channel().render(judgment, ctx))
        except Exception as exc:  # 一个渠道挂了不拖垮整条管线
            _log(ctx.archive_dir, f"{name} 渲染失败：{exc}")

    if not (ctx.archive_dir / "report.md").is_file():
        renders.append(_fallback_render(judgment, ctx))
    return renders


def _log(archive_dir: Path, message: str) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    with (archive_dir / "render.log").open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def _fallback_render(judgment: Judgment, ctx: RenderContext) -> RenderResult:
    ctx.archive_dir.mkdir(parents=True, exist_ok=True)
    text = f"# {ctx.date}\n\n最近怎么样：{judgment.summary}\n\n下一步怎么走：{judgment.advice}\n"
    path = ctx.archive_dir / "report.md"
    path.write_text(text, encoding="utf-8")
    return RenderResult(channel="fallback", output=text, artifacts=[path])


def _write_judgment(judgment: Judgment, archive_dir: Path) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "prompt.md").write_text(judgment.prompt, encoding="utf-8")
    (archive_dir / "judgment.json").write_text(
        json.dumps(judgment.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _read_judgment(archive_dir: Path) -> Judgment:
    path = archive_dir / "judgment.json"
    if not path.is_file():
        raise FileNotFoundError(f"{archive_dir} 还没有判断结果，先跑 `--stage judge`")
    return Judgment.from_dict(json.loads(path.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="step-ledger", description="把今天的收支素材变成一句有温度的复盘")
    parser.add_argument("--date", help="指定日期（YYYY-MM-DD），默认今天")
    parser.add_argument("--text", help="直接投递一段素材文字")
    parser.add_argument("--file", help="投递一个素材文件或目录")
    parser.add_argument("--source", action="append", help="额外收一个素材夹（可多次；给了就覆盖 COLLECT_SOURCE_DIRS）")
    parser.add_argument("--stdin", action="store_true", help="从 stdin 读素材")
    parser.add_argument("--root", help="项目根目录，默认当前目录或 STEP_LEDGER_ROOT")
    parser.add_argument("--stage", choices=("all", "collect", "judge", "render"), default="all")
    parser.add_argument("--provider", help="临时覆盖 JUDGE_PROVIDER（stub / openai）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出运行结果")
    parser.add_argument("--no-echo", action="store_true", help="不往终端打印渲染结果")
    args = parser.parse_args(argv)

    payload: str | Path | None = args.file or args.text
    if args.stdin:
        payload = sys.stdin.read()

    try:
        result = run(
            date=args.date,
            payload=payload,
            root=args.root,
            stage=args.stage,
            provider=args.provider,
            sources=args.source,
            echo=not (args.json or args.no_echo),
        )
    except FileNotFoundError as exc:
        print(f"step-ledger: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # 兜底：给 cron 一个非零退出码，日志里能看到原因
        print(f"step-ledger 运行失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
