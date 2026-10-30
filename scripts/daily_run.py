#!/usr/bin/env python3
"""cron 兜底入口：没有常驻 agent 时，由系统定时调用。

    .venv/bin/python scripts/daily_run.py

它与 agent 调用走的是同一条管线（step_ledger.pipeline.run），产物一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from step_ledger.pipeline import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
