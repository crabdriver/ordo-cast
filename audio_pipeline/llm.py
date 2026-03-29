from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .json_utils import parse_json_from_llm


class OpenAICompatibleTextClient:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise RuntimeError("请先安装 openai：pip install openai") from exc

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def render_prompt(self, template_path: Path, variables: Dict[str, Any]) -> str:
        """仅替换已知占位符 `{key}`，避免 str.format 与用户正文中的花括号冲突。"""
        text = template_path.read_text(encoding="utf-8")
        for key, value in variables.items():
            text = text.replace("{" + key + "}", str(value))
        return text

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
        data = parse_json_from_llm(raw)
        if isinstance(data, dict):
            return data
        raise ValueError("模型返回的不是 JSON 对象")

