from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from .config import SeriesDefinition, extract_numeric_prefix, strip_audio_prefix


@dataclass(frozen=True)
class AudioSource:
    series: SeriesDefinition
    source_path: Path
    source_id: str
    sequence: int
    title: str
    transcript_path: Path


def scan_audio_sources(series_definitions: Iterable[SeriesDefinition]) -> List[AudioSource]:
    discovered: List[AudioSource] = []
    for series in series_definitions:
        if not series.audio_dir.exists():
            continue

        audio_files = sorted(
            [
                path
                for path in series.audio_dir.iterdir()
                if path.is_file() and path.suffix.lower() == ".mp3" and not path.name.startswith(".")
            ],
            key=lambda path: (extract_numeric_prefix(path.name) or 10**9, path.name),
        )

        for path in audio_files:
            discovered.append(
                AudioSource(
                    series=series,
                    source_path=path,
                    source_id=f"{series.display_name}/{path.name}",
                    sequence=extract_numeric_prefix(path.name) or 0,
                    title=strip_audio_prefix(path.name),
                    transcript_path=series.build_transcript_path(path.name),
                )
            )
    return discovered

