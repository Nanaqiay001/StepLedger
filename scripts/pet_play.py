#!/usr/bin/env python3
"""让桌宠说一句：宿主 agent 的机械层。

判断层只给事实，说不说、怎么说、播什么，归 agent。这个脚本负责把话安全地送进
dsh-pet：surface 匹配、取锁、投喂、点播、等回执、释放、读回校验都在这儿。

    python scripts/pet_play.py --list
    python scripts/pet_play.py --text "今天工资到了，先留一小份不动" --anim "余额-数金皱眉"
    python scripts/pet_play.py --text "又超了啊" --meme "要不直接骂他"
    python scripts/pet_play.py --auto            # 无人值守：用当天 judgment.json 压一句
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_type
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from step_ledger.render.channels.pet import (  # noqa: E402
    DEFAULT_TIERS,
    PetClient,
    bubble_text,
    pick_animation,
    record_said,
    tiers_from,
)
from step_ledger.shared.config import Config  # noqa: E402
from step_ledger.shared.types import Judgment  # noqa: E402


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pet_play", description="让 dsh-pet 说一句（agent 用）")
    parser.add_argument("--text", help="要说的话；建议 ≤60 字")
    parser.add_argument("--anim", help="动画名；给 `--list` 里出现过的")
    parser.add_argument("--no-anim", action="store_true", help="不指定动画，用宠物自己的碎碎念动画")
    parser.add_argument("--meme", help="表情包名（可选，见 --list）")
    parser.add_argument("--duration", type=int, help="气泡停留毫秒数（默认 10000）")
    parser.add_argument("--list", action="store_true", help="列出可点播的动画与表情包")
    parser.add_argument("--auto", action="store_true", help="用当天 judgment.json 自动压一句话（兜底）")
    parser.add_argument("--date", help="--auto 用哪天的判断，默认今天")
    parser.add_argument("--pet", help="宠物 id，默认读 PET_ID")
    parser.add_argument("--base-url", help="覆盖 PET_BASE_URL")
    parser.add_argument("--root", help="项目根目录，默认当前目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return parser.parse_args(argv)


def _load_judgment(cfg: Config, date: str | None) -> tuple[Judgment | None, float | None]:
    run_date = date or date_type.today().isoformat()
    path = cfg.archive_for(run_date) / "judgment.json"
    if not path.is_file():
        return None, None
    data = json.loads(path.read_text(encoding="utf-8"))
    judgment = Judgment.from_dict(data)
    percent = ((judgment.meta or {}).get("progress") or {}).get("percent")
    return judgment, percent if isinstance(percent, (int, float)) else None


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    cfg = Config.load(args.root)
    base_url = (args.base_url or cfg.pet_base_url).strip()
    if not base_url:
        print("未配置 PET_BASE_URL（.env），无法连接 dsh-pet", file=sys.stderr)
        return 2

    client = PetClient(base_url, args.pet or cfg.pet_id)

    if args.list:
        animations, memes = client.catalog()
        if not animations and not memes:
            print("读不到宠物配置：dsh-pet 没运行，或 PET_ID / PET_BASE_URL 不对", file=sys.stderr)
            return 1
        print(f"可点播动画（{len(animations)}）：")
        print("  " + "、".join(animations))
        if memes:
            print(f"\n表情包（{len(memes)}）：")
            for name, desc in memes.items():
                print(f"  {name} — {desc}")
        return 0

    text = (args.text or "").strip()
    animation = None if args.no_anim else (args.anim or "").strip() or None

    if args.auto:
        judgment, percent = _load_judgment(cfg, args.date)
        if judgment is None:
            print("当天还没有 judgment.json，先跑管线", file=sys.stderr)
            return 1
        text = text or bubble_text(judgment.summary)
        if animation is None and not args.no_anim:
            tiers = tiers_from(cfg.pet_anim_tiers) or DEFAULT_TIERS
            animation = pick_animation(percent, tiers)

    if not text:
        print("--text 或 --auto 必须给一个", file=sys.stderr)
        return 2

    ok, detail = client.play(text, animation=animation, meme=args.meme, duration=args.duration)
    if ok:
        record_said(cfg.archive_for(args.date or date_type.today().isoformat()), text, animation)

    if args.json:
        print(json.dumps({"ok": ok, "detail": detail, "text": text, "animation": animation}, ensure_ascii=False))
    elif ok:
        suffix = f"（动画：{animation}）" if animation else ""
        print(f"✓ {detail}{suffix}")
        if len(text) > 60:
            print(f"  注意：这 {len(text)} 字有点长，气泡会挡屏幕", file=sys.stderr)
    else:
        print(f"✗ {detail}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
