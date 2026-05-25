from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .config import SeriesDefinition, build_title_identity
from .youtube_downloader import DEFAULT_OUTPUT_TEMPLATE


YOUTUBE_SOURCE_NAME_PATTERN = re.compile(r" \[[^\]]+\]\.(mp3|mp4|webm|m4a|mkv)$", re.IGNORECASE)
LEGACY_NUMBERED_SOURCE_PATTERN = re.compile(r"^\d{1,2}\.\s")
EVENTS_SOURCE_PATH_KEYS = ("source_path",)


def is_youtube_source_name(source_name: str) -> bool:
    return bool(YOUTUBE_SOURCE_NAME_PATTERN.search(source_name.strip()))


def truncate_title_to_bytes(title: str, max_bytes: int = 180) -> str:
    encoded = title.encode("utf-8")
    if len(encoded) <= max_bytes:
        return title
    truncated = encoded[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ""


def build_youtube_source_name(
    *,
    upload_date: str,
    title: str,
    video_id: str,
    ext: str = "mp3",
) -> str:
    safe_title = truncate_title_to_bytes(title.strip())
    date_part = upload_date.strip()
    if not date_part or date_part == "NA":
        raise ValueError(f"缺少 upload_date，无法构造 YouTube 文件名：{video_id}")
    return f"{date_part}. {safe_title} [{video_id}].{ext.lstrip('.')}"


def build_youtube_source_name_from_video(video: dict, *, ext: str = "mp3") -> str:
    return build_youtube_source_name(
        upload_date=str(video.get("upload_date") or ""),
        title=str(video.get("title") or ""),
        video_id=str(video.get("id") or ""),
        ext=ext,
    )


def load_youtube_name_overrides(overrides_path: Path) -> dict[tuple[str, str], str]:
    if not overrides_path.exists():
        return {}
    payload = json.loads(overrides_path.read_text(encoding="utf-8"))
    mapping: dict[tuple[str, str], str] = {}
    for item in payload.get("overrides") or []:
        if not isinstance(item, dict):
            continue
        series_key = str(item.get("series_key") or "").strip()
        title_key = str(item.get("title_key") or "").strip()
        source_name = str(item.get("source_name") or "").strip()
        if not series_key or not title_key or not source_name:
            continue
        if not is_youtube_source_name(source_name):
            raise ValueError(f"override source_name 不是 YouTube 格式：{source_name}")
        mapping[(series_key, title_key)] = source_name
    return mapping


def load_youtube_names_from_events(events_path: Path) -> dict[tuple[str, str], str]:
    if not events_path.exists():
        return {}
    mapping: dict[tuple[str, str], str] = {}
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        series_key = str(event.get("series_key") or "").strip()
        title_key = str(event.get("title_key") or "").strip()
        source_path = str(event.get("source_path") or "").strip()
        if not series_key or not title_key or not source_path:
            continue
        source_name = Path(source_path).name
        if not is_youtube_source_name(source_name):
            continue
        mapping[(series_key, title_key)] = source_name
    return mapping


def lookup_canonical_source_name(
    *,
    series_key: str,
    title_key: str,
    events_index: dict[tuple[str, str], str],
    playlist_index: dict[str, str],
    overrides_index: dict[tuple[str, str], str] | None = None,
) -> str | None:
    if overrides_index:
        override = overrides_index.get((series_key, title_key))
        if override:
            return override

    direct = events_index.get((series_key, title_key)) or playlist_index.get(title_key)
    if direct:
        return direct

    for (indexed_series, indexed_title), source_name in events_index.items():
        if indexed_series != series_key:
            continue
        if _title_keys_related(title_key, indexed_title):
            return source_name

    for indexed_title, source_name in playlist_index.items():
        if _title_keys_related(title_key, indexed_title):
            return source_name
    return None


def _title_keys_related(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right or left.startswith(right) or right.startswith(left):
        return True
    shorter, longer = sorted((left, right), key=len)
    return shorter in longer


def fetch_playlist_videos(
    channel_url: str,
    *,
    command_runner: Callable[[list[str]], str] | None = None,
) -> list[dict]:
    runner = command_runner or _default_playlist_runner
    payload = runner(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "-J",
            "--ignore-errors",
            "--extractor-args",
            "youtube:player_client=android",
            channel_url,
        ]
    )
    data = json.loads(payload)
    entries = data.get("entries") or []
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("id")]


def build_playlist_source_name_index(
    channel_url: str,
    series: SeriesDefinition,
    *,
    command_runner: Callable[[list[str]], str] | None = None,
    ext: str = "mp3",
) -> dict[str, str]:
    index: dict[str, str] = {}
    for video in fetch_playlist_videos(channel_url, command_runner=command_runner):
        try:
            source_name = build_youtube_source_name_from_video(video, ext=ext)
        except ValueError:
            continue
        title_key = series.build_title_identity(source_name).title_key
        index[title_key] = source_name
    return index


def _default_playlist_runner(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.stdout.strip():
        return completed.stdout
    detail = (completed.stderr or completed.stdout or "").strip()
    raise RuntimeError(detail or f"yt-dlp 退出码 {completed.returncode}")
