from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import uuid
from typing import Iterable, List

from audio_pipeline.config import sanitize_filename, sanitize_title, strip_audio_prefix
from audio_pipeline.json_utils import parse_articles_payload


HEADING_PATTERN = re.compile(r"^\s*#\s+.+?$", re.MULTILINE)


@dataclass(frozen=True)
class ArticleDraft:
    title: str
    body: str


def resolve_article_output_dir(base_dir: Path, series_name: str, source_dir_name: str | None = None) -> Path:
    series_dir = base_dir / sanitize_title(series_name)
    if not source_dir_name:
        return series_dir
    return series_dir / sanitize_filename(source_dir_name)


def derive_issue_number_from_entry(entry: dict) -> str:
    source_name = str(entry.get("source_name") or "")
    if source_name:
        prefix = Path(source_name).stem.split(".", 1)[0].strip()
        if prefix:
            return prefix.zfill(2) if len(prefix) <= 2 and prefix.isdigit() else prefix
    sequence = entry.get("sequence")
    if isinstance(sequence, int):
        return str(sequence).zfill(2)
    if isinstance(sequence, str) and sequence.isdigit():
        return sequence.zfill(2)
    return "00"


def derive_article_source_dir_name(entry: dict) -> str:
    source_name = str(entry.get("source_name") or "")
    if source_name:
        return sanitize_filename(Path(source_name).stem)
    issue_number = derive_issue_number_from_entry(entry)
    display_title = sanitize_title(str(entry.get("display_title") or "").strip())
    if not display_title:
        display_title = sanitize_title(strip_audio_prefix(source_name))
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


def list_issue_article_files(output_dir: Path, issue_number: str) -> List[Path]:
    if not output_dir.exists():
        return []
    return sorted(
        path
        for path in output_dir.glob(f"{issue_number}-*.md")
        if path.is_file()
    )


def validate_article_drafts(drafts: Iterable[ArticleDraft], *, expected_count: int | None = None) -> List[ArticleDraft]:
    normalized = [ArticleDraft(title=draft.title.strip(), body=draft.body.strip()) for draft in drafts]
    if not normalized:
        raise ValueError("模型未返回任何文章。")
    if expected_count is not None and len(normalized) != expected_count:
        raise ValueError(f"拆稿篇数 {len(normalized)} 与要求 {expected_count} 不一致。")
    seen_filenames: set[str] = set()
    for index, draft in enumerate(normalized, start=1):
        if not draft.title:
            raise ValueError(f"第 {index} 篇标题为空。")
        if not draft.body:
            raise ValueError(f"第 {index} 篇正文为空。")
        safe_title = sanitize_title(draft.title)
        if not safe_title:
            raise ValueError(f"第 {index} 篇标题清洗后为空。")
        if safe_title in seen_filenames:
            raise ValueError(f"第 {index} 篇标题与前文冲突，生成后文件名会重复：{safe_title}")
        seen_filenames.add(safe_title)
    return normalized


def write_articles(output_dir: Path, issue_number: str, drafts: Iterable[ArticleDraft]) -> List[Path]:
    normalized = validate_article_drafts(drafts)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"目标文章目录非空，拒绝覆盖：{output_dir}")
    if output_dir.exists():
        output_dir.rmdir()

    staging_dir = output_dir.parent / f".{output_dir.name}.staging-{uuid.uuid4().hex[:8]}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    written_names: List[str] = []
    try:
        for index, draft in enumerate(normalized, start=1):
            safe_title = sanitize_title(draft.title)
            filename = f"{issue_number}-{index:02d}_{safe_title}.md"
            path = staging_dir / filename
            path.write_text(strip_title_heading(draft.body).strip() + "\n", encoding="utf-8")
            written_names.append(filename)
        staging_dir.rename(output_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return [output_dir / name for name in written_names]


def parse_article_drafts(raw_payload: str) -> List[ArticleDraft]:
    items = parse_articles_payload(raw_payload)
    drafts: List[ArticleDraft] = []
    for item in items:
        title = str(item.get("title", "")).strip()
        body = str(item.get("body", "")).strip()
        drafts.append(ArticleDraft(title=title, body=body))
    return drafts
