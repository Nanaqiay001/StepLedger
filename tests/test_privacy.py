"""公开仓库强制项：仓库内不得出现凭证与私人信息。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.privacy_scan import scan  # noqa: E402


def test_repository_is_clean() -> None:
    assert scan(ROOT) == []
