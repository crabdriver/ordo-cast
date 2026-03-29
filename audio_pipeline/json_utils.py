from __future__ import annotations

import json
from typing import Any


def strip_llm_json_fences(text: str) -> str:
    """Remove common Markdown code fences around JSON from LLM output."""
    s = text.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        else:
            s = s[3:]
    s = s.strip()
    if s.endswith("```"):
        s = s[: -3].rstrip()
    return s.strip()


def parse_json_from_llm(text: str) -> Any:
    """
    Parse JSON from LLM text: strip fences, then try full parse,
    then substring between matching braces or brackets.
    """
    s = strip_llm_json_fences(text)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        return json.loads(s[start : end + 1])
    start, end = s.find("["), s.rfind("]")
    if start >= 0 and end > start:
        return json.loads(s[start : end + 1])
    raise json.JSONDecodeError("无法从模型输出中解析 JSON", s, 0)


def parse_articles_payload(raw: str) -> list[dict[str, Any]]:
    """Return list of article dicts from split-wechat JSON."""
    data = parse_json_from_llm(raw)
    if isinstance(data, dict) and isinstance(data.get("articles"), list):
        return [x for x in data["articles"] if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    raise KeyError("articles")
