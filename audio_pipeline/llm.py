from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from .json_utils import parse_json_from_llm


def _normalize_openai_base_url(base_url: str) -> str:
    """OpenAI SDK 需要 base_url 指向 …/v1；仅当 host 后无路径时自动补全。"""
    base_url = base_url.strip()
    path = (urlparse(base_url).path or "").rstrip("/")
    if path == "":
        return base_url.rstrip("/") + "/v1"
    return base_url


class OpenAICompatibleTextClient:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise RuntimeError("请先安装 openai：pip install openai") from exc

        base_url = _normalize_openai_base_url(base_url)
        # 部分聚合网关（如 ikuncode）对 chat 接口做「客户端」校验：未在白名单的 User-Agent 会返回
        # 403 blocked 或 400 Client not allowed。未设置 CONTENT_LLM_USER_AGENT 时使用 OpenAI SDK 默认 UA
        #（可用 `python -c "import openai; print(openai.OpenAI(api_key='x',base_url='http://x/v1').user_agent)"` 查看）。
        # 设 CONTENT_LLM_USER_AGENT=- 显式不注入自定义头（同上）。
        ua = os.getenv("CONTENT_LLM_USER_AGENT", "").strip()
        if ua == "-":
            ua = ""
        kwargs: dict[str, Any] = dict(api_key=api_key, base_url=base_url)
        if ua:
            kwargs["default_headers"] = {"User-Agent": ua}
        self._client = OpenAI(**kwargs)
        self._model = model

    def render_prompt(self, template_path: Path, variables: Dict[str, Any]) -> str:
        """仅替换已知占位符 `{key}`，避免 str.format 与用户正文中的花括号冲突。"""
        text = template_path.read_text(encoding="utf-8")
        for key, value in variables.items():
            text = text.replace("{" + key + "}", str(value))
        return text

    def complete_text(self, *, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
        except Exception as exc:
            err = str(exc).lower()
            if "blocked" in err or "client not allowed" in err:
                raise RuntimeError(
                    "上游网关拒绝了当前 HTTP 客户端（常见于 User-Agent / 客户端白名单）。"
                    "请到 ikuncode（或你使用的聚合网关）控制台，为该令牌关闭「客户端限制」"
                    "或把 OpenAI Python SDK 的 User-Agent（形如 OpenAI/Python x.y.z）加入允许列表；"
                    "也可在 .env 设置 CONTENT_LLM_USER_AGENT 为控制台允许的 UA。"
                ) from exc
            raise
        return response.choices[0].message.content or ""

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        raw = self.complete_text(system_prompt=system_prompt, user_prompt=user_prompt).strip()
        data = parse_json_from_llm(raw)
        if isinstance(data, dict):
            return data
        raise ValueError("模型返回的不是 JSON 对象")

