"""配置：只从 `.env` + 环境变量读，带安全默认值。

设计上不引入 dotenv 依赖：`.env` 是 KEY=VALUE 的简单格式，十几行就能读。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_KEYS = (
    "JUDGE_PROVIDER",
    "JUDGE_API_KEY",
    "JUDGE_MODEL",
    "JUDGE_BASE_URL",
    "PIPELINE_DAILY_RUN_TIME",
    "PIPELINE_LOOKBACK_DAYS",
    "COLLECT_MATERIALS_DIR",
    "RENDER_CHANNELS",
    "RENDER_ARCHIVE_DIR",
)

DEFAULT_TARGET = 1_000_000


def _load_dotenv(path: Path) -> None:
    """把 `.env` 读进 os.environ；已有环境变量优先，不覆盖。"""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    root: Path
    materials_dir: Path
    archive_dir: Path
    provider: str
    api_key: str
    model: str
    base_url: str
    daily_run_time: str
    lookback_days: int
    channels: tuple[str, ...]

    @property
    def profile_path(self) -> Path:
        return self.materials_dir / "profile.md"

    def materials_for(self, date: str) -> Path:
        return self.materials_dir / date

    def archive_for(self, date: str) -> Path:
        return self.archive_dir / date

    @classmethod
    def load(cls, root: Path | str | None = None) -> "Config":
        root_path = Path(root or os.getenv("STEP_LEDGER_ROOT") or Path.cwd()).expanduser().resolve()
        _load_dotenv(root_path / ".env")

        materials = _resolve(root_path, os.getenv("COLLECT_MATERIALS_DIR"), "materials")
        archive = _resolve(root_path, os.getenv("RENDER_ARCHIVE_DIR"), "archive")
        channels = tuple(
            c.strip() for c in (os.getenv("RENDER_CHANNELS") or "console").split(",") if c.strip()
        )
        return cls(
            root=root_path,
            materials_dir=materials,
            archive_dir=archive,
            provider=(os.getenv("JUDGE_PROVIDER") or "stub").strip().lower(),
            api_key=(os.getenv("JUDGE_API_KEY") or "").strip(),
            model=(os.getenv("JUDGE_MODEL") or "gpt-4o-mini").strip(),
            base_url=(os.getenv("JUDGE_BASE_URL") or "https://api.openai.com/v1").strip(),
            daily_run_time=(os.getenv("PIPELINE_DAILY_RUN_TIME") or "21:00").strip(),
            lookback_days=_as_int(os.getenv("PIPELINE_LOOKBACK_DAYS"), 1),
            channels=channels or ("console",),
        )


def _resolve(root: Path, value: str | None, default: str) -> Path:
    if not value:
        return (root / default).resolve()
    path = Path(value).expanduser()
    return path if path.is_absolute() else (root / path).resolve()
