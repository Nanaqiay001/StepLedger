#!/usr/bin/env python3
"""公开仓库发布前的隐私扫描：零匹配才算过。

    python scripts/privacy_scan.py

检查项：真实 API key、手机号、邮箱、本机绝对路径、被误纳入版本控制的 `.env`。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "materials", "archive", "dist", "build"}

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("API key", re.compile(r"\b(?:sk|ghp|glpat)-[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    ("本机绝对路径", re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/")),
]


def _candidate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name == ".env":
            continue  # 凭证文件本身允许有 key，但不能被提交；下面单独检查
        files.append(path)
    return files


def _env_tracked(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", ".env"],
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def scan(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    if _env_tracked(root):
        findings.append(".env: 凭证文件被纳入版本控制")
    for path in _candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pattern in RULES:
                if pattern.search(line):
                    findings.append(f"{path.relative_to(root)}:{lineno}: {name}")
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("隐私扫描未通过：")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print("隐私扫描通过：零匹配")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
