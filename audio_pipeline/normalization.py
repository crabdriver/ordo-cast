from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Optional


TIMESTAMP_PATTERN = re.compile(r"\[\d{2}:\d{2}:\d{2}\]")
MULTISPACE_PATTERN = re.compile(r"[ \t]+")
MULTIBLANK_PATTERN = re.compile(r"\n{3,}")


def scrub_transcript_text(raw_text: str) -> str:
    cleaned = TIMESTAMP_PATTERN.sub("", raw_text)
    lines = [MULTISPACE_PATTERN.sub(" ", line).strip() for line in cleaned.splitlines()]
    nonempty = []
    blank_streak = 0
    for line in lines:
        if not line:
            blank_streak += 1
            if blank_streak <= 1:
                nonempty.append("")
            continue
        blank_streak = 0
        nonempty.append(line)
    merged = "\n".join(nonempty).strip()
    return MULTIBLANK_PATTERN.sub("\n\n", merged)


def compute_text_checksum(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def should_skip_normalization(*, existing_text: Optional[str], entry: dict, force: bool) -> bool:
    if force:
        return False
    if entry.get("review_status") == "reviewed":
        return True
    known_checksum = entry.get("transcript_checksum")
    if existing_text is not None and known_checksum and compute_text_checksum(existing_text) != known_checksum:
        return True
    if entry.get("normalization_status") == "completed":
        return True
    return False


def build_normalization_manifest_update(*, previous_entry: dict, markdown: str) -> dict:
    return {
        "normalization_status": "completed",
        "review_status": "pending",
        "transcript_checksum": compute_text_checksum(markdown),
        "normalization_error": None,
        "article_status": "pending",
        "article_paths": [],
        "article_error": None,
    }


def format_transcript_markdown(
    *,
    series_name: str,
    source_name: str,
    cleaned_text: str,
    reviewed: bool,
) -> str:
    review_status = "已复核" if reviewed else "待复核"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"系列：{series_name}\n"
        f"原音频：{source_name}\n"
        f"状态：{review_status}\n"
        f"转录时间：{timestamp}\n\n"
        "---\n\n"
        f"{cleaned_text.strip()}\n"
    )

