from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class OpenAICompatibleTextClient:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise RuntimeError("请先安装 openai：pip install openai") from exc

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def render_prompt(self, template_path: Path, variables: Dict[str, Any]) -> str:
        template = template_path.read_text(encoding="utf-8")
        return template.format(**variables)

    def complete_text(self, *, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        raw = self.complete_text(system_prompt=system_prompt, user_prompt=user_prompt).strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.endswith("```"):
            raw = raw[:-3]
        return json.loads(raw.strip())

