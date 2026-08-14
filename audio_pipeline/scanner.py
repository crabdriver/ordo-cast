from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, List

from .config import SeriesDefinition, extract_sequence_prefix


@dataclass(frozen=True)
class AudioSource:
    series: SeriesDefinition
    source_path: Path
    source_id: str
    title_key: str
    sequence: int
    title: str
    transcript_path: Path
    audio_size: int
    audio_mtime_ns: int


def scan_audio_sources(series_definitions: Iterable[SeriesDefinition]) -> List[AudioSource]:
    discovered: List[AudioSource] = []
    for series in series_definitions:
        if not series.audio_dir.exists():
            continue

        allowed_extensions = {".mp3", ".m4a", ".mp4", ".mov", ".wav", ".webm", ".aac"}
        audio_files = sorted(
            [
                path
                for path in series.audio_dir.iterdir()
                if path.is_file() and path.suffix.lower() in allowed_extensions and not path.name.startswith(".")
            ],
            key=lambda path: (extract_sequence_prefix(path.name) or 10**9, path.name),
        )

        # 校验：检查是否存在未下载完的同源视频临时文件 (.part / .ytdl)
        filtered_audio_files = []
        for path in audio_files:
            yt_id_match = re.search(r"\[([a-zA-Z0-9_-]{11})\]", path.name)
            if yt_id_match:
                yt_id = yt_id_match.group(1)
                part_files = list(series.audio_dir.glob(f"*{yt_id}*.part"))
                ytdl_files = list(series.audio_dir.glob(f"*{yt_id}*.ytdl"))
                if part_files or ytdl_files:
                    # 说明视频下载尚未真正结束，属于残留不完整文件，必须跳过扫描
                    continue
            filtered_audio_files.append(path)

        grouped: dict[str, list[tuple[Path, int | None, str]]] = {}
        for path in filtered_audio_files:
            identity = series.build_title_identity(path.name)
            grouped.setdefault(identity.title_key, []).append((path, extract_sequence_prefix(path.name), identity.display_title))

        for title_key, candidates in grouped.items():
            try:
                source_path = max(candidates, key=lambda item: (item[0].stat().st_mtime_ns, item[0].name))[0]
                display_title = candidates[0][2]
                known_sequences = [sequence for _, sequence, _ in candidates if sequence is not None]
                sequence = min(known_sequences) if known_sequences else 0
                stat = source_path.stat()
            except FileNotFoundError:
                continue
            discovered.append(
                AudioSource(
                    series=series,
                    source_path=source_path,
                    source_id=f"{series.key}/{title_key}",
                    title_key=title_key,
                    sequence=sequence,
                    title=display_title,
                    transcript_path=series.build_transcript_path(source_path.name),
                    audio_size=stat.st_size,
                    audio_mtime_ns=stat.st_mtime_ns,
                )
            )
    return discovered

