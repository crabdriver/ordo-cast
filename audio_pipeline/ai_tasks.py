from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from .article_splitter import ArticleDraft, parse_article_drafts
from .llm import OpenAICompatibleTextClient
from .normalization import scrub_transcript_text


TRANSCRIPT_SYSTEM_PROMPT = "你是专业的中文录音整理编辑，请把口语转成适合后续拆稿的长稿，不要杜撰。"
ARTICLE_SYSTEM_PROMPT = "你是专业的公众号编辑，请严格遵守给定规则输出结构化 JSON。"


def build_text_client_from_env() -> Optional[OpenAICompatibleTextClient]:
    api_key = os.getenv("CONTENT_LLM_API_KEY")
    base_url = os.getenv("CONTENT_LLM_BASE_URL")
    model = os.getenv("CONTENT_LLM_MODEL")
    if not api_key or not base_url or not model:
        return None
    return OpenAICompatibleTextClient(api_key=api_key, base_url=base_url, model=model)


def llm_cleanup_transcript(
    *,
    client: Optional[OpenAICompatibleTextClient],
    prompt_path: Path,
    series_name: str,
    source_name: str,
    raw_transcript: str,
) -> str:
    if client is None:
        return scrub_transcript_text(raw_transcript)

    prompt = client.render_prompt(
        prompt_path,
        {
            "series_name": series_name,
            "source_name": source_name,
            "raw_transcript": raw_transcript,
        },
    )
    result = client.complete_text(system_prompt=TRANSCRIPT_SYSTEM_PROMPT, user_prompt=prompt).strip()
    return result or scrub_transcript_text(raw_transcript)


def llm_generate_articles(
    *,
    client: OpenAICompatibleTextClient,
    prompt_path: Path,
    issue_number: str,
    transcript_text: str,
    principles_text: str = "",
) -> List[ArticleDraft]:
    prompt = client.render_prompt(
        prompt_path,
        {
            "issue_number": issue_number,
            "transcript_text": transcript_text,
            "principles_text": principles_text,
        },
    )
    payload = client.complete_text(system_prompt=ARTICLE_SYSTEM_PROMPT, user_prompt=prompt)
    return parse_article_drafts(payload)

