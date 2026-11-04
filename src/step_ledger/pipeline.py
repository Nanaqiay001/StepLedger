"""管线编排：采集 → 判断 → 渲染。两个入口（agent / cron）都走这里。

每一层都可以单独重跑（`--stage`），同日重复执行覆盖当天产物，不新建日期目录。

判断层负责算事实：`secretary.run()` 会先观察余额、再算已花与额度、最后让模型说话。
所以渲染层拿到的 `Judgment` 里已经带着数字，不需要再去翻 `archive/`。

重算为准：`judgment.json` 是缓存。`--stage render` 发现档案比判断结果新、
或旧归档还没有事实快照时，会先把这一天重算一遍再排版。
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
from .judge import secretary
from .judge.history import History
from .judge.providers.openai_compatible import OpenAICompatibleProvider
from .judge.providers.stub import StubProvider
from .render.channels.console import ConsoleChannel
from .render.channels.pet import PetChannel, recent_said
from .shared.config import Config
from .shared.profile import Profile, ensure_profile, load_profile
from .shared.types import CollectResult, Judgment, PipelineResult, RenderContext, RenderResult


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
    force: bool = False,
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
        result.skipped.extend(result.judgment.runtime.get("skipped") or [])
        _write_judgment(result.judgment, archive_dir)

    if stage in ("all", "render"):
        if result.judgment is None:
            result.judgment = _read_judgment(archive_dir)
        mode = _refresh_mode(
            cfg, archive_dir, result.judgment, materials_dir, force=force and stage == "render"
        )
        if mode == "judge":
            # 档案改过或素材还在：整份重算，让数字和话重新同源
            result.judgment = _judge(cfg, materials_dir, profile, run_date, provider)
            _write_judgment(result.judgment, archive_dir)
        elif mode == "facts":
            # 旧归档补事实：素材已经没了，别用模板话覆盖当初模型写的
            result.judgment = secretary.backfill(
                judgment=result.judgment,
                profile=profile,
                date=run_date,
                history=History(cfg.archive_dir, day=run_date),
            )
            _write_judgment(result.judgment, archive_dir)
        ctx = RenderContext(
            out_dir=archive_dir,
            echo=echo,
            recent_said=recent_said(archive_dir),
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


def _judge(
    cfg: Config,
    materials_dir: Path,
    profile: Profile,
    run_date: str,
    override: str | None,
) -> Judgment:
    requested = (override or cfg.provider or "stub").strip().lower()
    provider_error = None
    if material_files(materials_dir):
        try:
            provider = _build_provider(cfg, requested)
        except Exception as exc:  # 没配 key / 未知 provider：降级但仍算出事实
            provider = StubProvider()
            provider_error = f"模型不可用：{exc}"
    else:
        provider = StubProvider()

    return secretary.run(
        materials_dir=materials_dir,
        profile=profile,
        date=run_date,
        provider=provider,
        history=History(cfg.archive_dir, day=run_date),
        requested=requested,
        profile_created=profile.created,
        backfilled=run_date < date_type.today().isoformat(),
        provider_error=provider_error,
    )


def _build_provider(cfg: Config, name: str):
    if name in ("stub", "offline", "none"):
        return StubProvider()
    if name in ("openai", "openai_compatible", "compatible"):
        return OpenAICompatibleProvider(cfg.api_key, cfg.model, cfg.base_url)
    raise ProviderError(f"未知的 JUDGE_PROVIDER：{name}")


def _refresh_mode(
    cfg: Config, archive_dir: Path, judgment: Judgment, materials_dir: Path, *, force: bool = False
) -> str | None:
    """要不要在渲染前重算，以及重算到什么程度。

    - `judge`：整份重算（档案改过，或旧归档但素材还在）
    - `facts`：只补事实（旧归档且素材已清理，保住当初的话）
    - `None`：不用动
    """
    if judgment.facts is None or force:
        return "judge" if material_files(materials_dir) else "facts"
    verdict = archive_dir / "judgment.json"
    try:
        if cfg.profile_path.stat().st_mtime_ns > verdict.stat().st_mtime_ns:
            return "judge"
    except OSError:
        return None
    return None


def _render(cfg: Config, judgment: Judgment, ctx: RenderContext) -> list[RenderResult]:
    renders: list[RenderResult] = []
    for name in cfg.channels:
        channel = {
            "console": ConsoleChannel,
            "pet": lambda: PetChannel(cfg.pet_base_url, cfg.pet_id, cfg.pet_anim_tiers),
        }.get(name)
        if channel is None:
            _log(ctx.out_dir, f"未知渠道，已跳过：{name}")
            continue
        try:
            renders.append(channel().render(judgment, ctx))
        except Exception as exc:  # 一个渠道挂了不拖垮整条管线
            _log(ctx.out_dir, f"{name} 渲染失败：{exc}")

    if not (ctx.out_dir / "report.md").is_file():
        renders.append(_fallback_render(judgment, ctx))
    return renders


def _log(archive_dir: Path, message: str) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    with (archive_dir / "render.log").open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def _fallback_render(judgment: Judgment, ctx: RenderContext) -> RenderResult:
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    day = judgment.facts.date if judgment.facts is not None else ""
    text = f"# {day}\n\n最近怎么样：{judgment.summary}\n\n下一步怎么走：{judgment.advice}\n"
    path = ctx.out_dir / "report.md"
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


def rebuild(*, root: Path | str | None = None, provider: str | None = None, echo: bool = False) -> list[PipelineResult]:
    """全量重算：逐天重跑判断层与渲染层。

    显式操作，会为每个有素材的日子调用一次模型；素材已清理的日子只补事实，
    不会用模板话覆盖当初写的内容。
    """
    cfg = Config.load(root)
    results: list[PipelineResult] = []
    for day_dir in sorted(cfg.archive_dir.iterdir()):
        if not day_dir.is_dir() or not (day_dir / "judgment.json").is_file():
            continue
        results.append(
            run(
                date=day_dir.name,
                stage="render",
                provider=provider,
                echo=echo,
                config=cfg,
                force=True,
            )
        )
    return results


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
    parser.add_argument("--rebuild", action="store_true", help="全量重算所有归档日（每天一次模型调用）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出运行结果")
    parser.add_argument("--no-echo", action="store_true", help="不往终端打印渲染结果")
    args = parser.parse_args(argv)

    if args.rebuild:
        results = rebuild(root=args.root, provider=args.provider, echo=not args.no_echo)
        print(f"重算：共 {len(results)} 天")
        return 0

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

    # 采集这层最容易静默出错：0 份素材也得说出来，别让人对着空气写总结
    summary = f"采集：共 {len(material_files(result.materials_dir))} 份素材"
    if result.skipped:
        summary += "；" + "；".join(result.skipped)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
