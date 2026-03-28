from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable, List


TITLE_CLEANUP_PATTERN = re.compile(r"[「」【】\[\]（）()<>《》]")
WHITESPACE_PATTERN = re.compile(r"\s+")
NUMERIC_PREFIX_PATTERN = re.compile(r"^\s*(\d+)")


@dataclass(frozen=True)
class SeriesDefinition:
    key: str
    display_name: str
    audio_dir: Path
    transcript_dir: Path
    prefix_width: int = 2

    def build_transcript_path(self, source_name: str) -> Path:
        sequence = extract_numeric_prefix(source_name) or 0
        title = strip_audio_prefix(source_name)
        safe_title = sanitize_title(title)
        return self.transcript_dir / f"{sequence:0{self.prefix_width}d}_{safe_title}.md"


@dataclass(frozen=True)
class PipelinePaths:
    workspace_root: Path
    manifest_path: Path
    raw_transcript_dir: Path
    article_dir: Path
    prompts_dir: Path
    series_map_path: Path

    @classmethod
    def from_workspace(cls, workspace_root: Path) -> "PipelinePaths":
        return cls(
            workspace_root=workspace_root,
            manifest_path=workspace_root / ".pipeline" / "manifest.json",
            raw_transcript_dir=workspace_root / ".pipeline" / "raw_transcripts",
            article_dir=workspace_root / "拆解后文章",
            prompts_dir=workspace_root / "prompts",
            series_map_path=workspace_root / ".pipeline" / "series_map.json",
        )


def extract_numeric_prefix(name: str) -> int | None:
    match = NUMERIC_PREFIX_PATTERN.match(name)
    return int(match.group(1)) if match else None


def strip_audio_prefix(source_name: str) -> str:
    stem = Path(source_name).stem
    stem = re.sub(r"^\s*\d+\s*[\.\-_、]*\s*", "", stem)
    stem = TITLE_CLEANUP_PATTERN.sub("", stem)
    stem = stem.replace("·", "")
    stem = WHITESPACE_PATTERN.sub(" ", stem).strip()
    return stem or "未命名转录稿"


def sanitize_title(title: str) -> str:
    sanitized = TITLE_CLEANUP_PATTERN.sub("", title)
    sanitized = sanitized.replace("/", " ").replace("\\", " ")
    sanitized = sanitized.replace(":", " ").replace("*", " ")
    sanitized = sanitized.replace("?", " ").replace('"', " ")
    sanitized = sanitized.replace("|", " ").replace("·", "")
    sanitized = WHITESPACE_PATTERN.sub(" ", sanitized).strip()
    return sanitized


def load_series_map(series_map_path: Path) -> List[SeriesDefinition]:
    data = json.loads(series_map_path.read_text(encoding="utf-8"))
    workspace_root = series_map_path.parent.parent
    series: List[SeriesDefinition] = []
    for item in data.get("series", []):
        audio_dir = Path(item["audio_dir"])
        transcript_dir = Path(item["transcript_dir"])
        if not audio_dir.is_absolute():
            audio_dir = workspace_root / audio_dir
        if not transcript_dir.is_absolute():
            transcript_dir = workspace_root / transcript_dir
        series.append(
            SeriesDefinition(
                key=item["key"],
                display_name=item["display_name"],
                audio_dir=audio_dir,
                transcript_dir=transcript_dir,
                prefix_width=item.get("prefix_width", 2),
            )
        )
    return series


def write_default_series_map(
    series_map_path: Path,
    workspace_root: Path,
    series_audio_dirs: Iterable[tuple[str, str, str]],
) -> None:
    payload = {"series": []}
    for key, display_name, audio_dir in series_audio_dirs:
        payload["series"].append(
            {
                "key": key,
                "display_name": display_name,
                "audio_dir": audio_dir,
                "transcript_dir": display_name,
                "prefix_width": 2,
            }
        )
    series_map_path.parent.mkdir(parents=True, exist_ok=True)
    series_map_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

