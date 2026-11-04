"""OpenAI 兼容的 provider：一个 POST /chat/completions 就够，不引第三方 SDK。

任何 OpenAI 兼容网关（官方 / 自建 / 代理）都能用，改 JUDGE_BASE_URL 即可。

两个动作共用同一层 HTTP：
- `observe()` 只读余额，温度 0（抽取要稳，不要创意）
- `judge()` 写总结与建议，温度 0.7（说话要有人味）
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..base import BaseProvider, ProviderError
from ..observe import OBSERVE_SYSTEM_PROMPT, build_observe_prompt, parse_observation_response
from ..prompt import SYSTEM_PROMPT, build_prompt, parse_judgment_response, read_materials
from ...shared.profile import Profile
from ...shared.types import Judgment, Observation


class OpenAICompatibleProvider(BaseProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 60.0) -> None:
        if not api_key:
            raise ProviderError("JUDGE_API_KEY 未配置")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def observe(self, materials_text: str, date: str = "") -> Observation:
        """只读余额。核验（摘录是否可寻址）由 secretary 统一做。"""
        content, _ = self._chat(
            OBSERVE_SYSTEM_PROMPT,
            build_observe_prompt(materials_text, date),
            temperature=0.0,
        )
        try:
            return parse_observation_response(content)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

    def judge(self, materials_dir: Path, profile: Profile, date: str = "") -> Judgment:
        text, skipped = read_materials(materials_dir)
        files = [p for p in materials_dir.iterdir() if p.is_file() and p.name != "profile.md"] if materials_dir.is_dir() else []
        prompt = build_prompt(profile, text, date, len(files))

        content, usage = self._chat(SYSTEM_PROMPT, prompt)
        try:
            summary, advice, balance = parse_judgment_response(content)
        except ValueError as exc:
            raise ProviderError(str(exc)) from exc

        return Judgment(
            summary=summary,
            advice=advice,
            prompt=prompt,
            runtime={
                "provider": self.name,
                "model": self.model,
                "material_count": len(files),
                "skipped": skipped,
                # 模型从素材里读到的账户余额；没读到就是 None。
                # 事实快照用 observe() 的结果，这个字段只为兼容旧归档保留。
                "balance": balance,
                # 顺手记下 token 用量，方便对账 / 看这次调用花了多少
                "usage": usage,
            },
        )

    def _chat(self, system: str, user: str, *, temperature: float = 0.7) -> tuple[str, dict[str, Any]]:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"请求失败：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError("网关返回的不是 JSON") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("返回结构不符合 OpenAI 约定") from exc
        return str(content), data.get("usage") or {}


__all__ = ["OpenAICompatibleProvider"]
