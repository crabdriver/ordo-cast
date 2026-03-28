from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable, List

from .config import sanitize_title


HEADING_PATTERN = re.compile(r"^\s*#\s+.+?$", re.MULTILINE)


@dataclass(frozen=True)
class ArticleDraft:
    title: str
    body: str


def resolve_article_output_dir(base_dir: Path, series_name: str) -> Path:
    if series_name == "天地大道":
        return base_dir
    return base_dir / sanitize_title(series_name)


def should_generate_articles(entry: dict, *, allow_pending_review: bool) -> bool:
    if entry.get("status") != "completed":
        return False
    if entry.get("article_status") == "completed":
        return False
    if entry.get("review_status") != "reviewed" and not allow_pending_review:
        return False
    return True


def strip_title_heading(body: str) -> str:
    lines = body.splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def write_articles(output_dir: Path, issue_number: str, drafts: Iterable[ArticleDraft]) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for index, draft in enumerate(drafts, start=1):
        safe_title = sanitize_title(draft.title)
        path = output_dir / f"{issue_number}-{index:02d}_{safe_title}.md"
        if path.exists():
            raise FileExistsError(f"目标文章已存在，拒绝覆盖：{path}")
        path.write_text(strip_title_heading(draft.body).strip() + "\n", encoding="utf-8")
        written.append(path)
    return written


def parse_article_drafts(raw_payload: str) -> List[ArticleDraft]:
    text = raw_payload.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.endswith("```"):
        text = text[:-3]
    data = json.loads(text.strip())
    items = data["articles"] if isinstance(data, dict) else data
    drafts: List[ArticleDraft] = []
    for item in items:
        drafts.append(ArticleDraft(title=item["title"].strip(), body=item["body"].strip()))
    return drafts

