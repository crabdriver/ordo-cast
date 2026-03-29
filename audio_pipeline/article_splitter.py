from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, List

from .config import sanitize_title, strip_audio_prefix
from .json_utils import parse_articles_payload


HEADING_PATTERN = re.compile(r"^\s*#\s+.+?$", re.MULTILINE)


@dataclass(frozen=True)
class ArticleDraft:
    title: str
    body: str


def resolve_article_output_dir(base_dir: Path, series_name: str, source_dir_name: str | None = None) -> Path:
    series_dir = base_dir / sanitize_title(series_name)
    if not source_dir_name:
        return series_dir
    return series_dir / sanitize_title(source_dir_name)


def derive_issue_number_from_entry(entry: dict) -> str:
    sequence = entry.get("sequence")
    if isinstance(sequence, int):
        return str(sequence).zfill(2)
    if isinstance(sequence, str) and sequence.isdigit():
        return sequence.zfill(2)
    source_name = str(entry.get("source_name") or "")
    prefix = source_name.split(".", 1)[0].strip()
    return prefix.zfill(2) if prefix.isdigit() else prefix


def derive_article_source_dir_name(entry: dict) -> str:
    issue_number = derive_issue_number_from_entry(entry)
    display_title = sanitize_title(str(entry.get("display_title") or "").strip())
    if not display_title:
        display_title = sanitize_title(strip_audio_prefix(str(entry.get("source_name") or "")))
    display_title = display_title or "未命名转录稿"
    return f"{issue_number}_{display_title}"


def inspect_article_output_state(entry: dict) -> str:
    article_paths = [Path(path) for path in entry.get("article_paths") or [] if path]
    if not article_paths:
        return "none"
    existing_count = sum(1 for path in article_paths if path.exists())
    if existing_count == len(article_paths):
        return "all_present"
    if existing_count == 0:
        return "all_missing"
    return "partial"


def should_generate_articles(entry: dict, *, allow_pending_review: bool) -> bool:
    if entry.get("status") != "completed":
        return False
    if inspect_article_output_state(entry) == "all_present":
        return False
    review = entry.get("review_status")
    if review == "pending" and not allow_pending_review:
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
    items = parse_articles_payload(raw_payload)
    drafts: List[ArticleDraft] = []
    for item in items:
        title = str(item.get("title", "")).strip()
        body = str(item.get("body", "")).strip()
        drafts.append(ArticleDraft(title=title or "未命名", body=body))
    return drafts

