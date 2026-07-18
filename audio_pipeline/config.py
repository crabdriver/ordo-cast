from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Iterable, List


TITLE_CLEANUP_PATTERN = re.compile(r"[「」【】\[\]（）()<>《》]")
WHITESPACE_PATTERN = re.compile(r"\s+")
NUMERIC_PREFIX_PATTERN = re.compile(r"^\s*(\d+)")
INVALID_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|]')
YOUTUBE_ID_SUFFIX_PATTERN = re.compile(r"\s+\[[^\]]+\]$")
TITLE_KEY_FILTER_PATTERN = re.compile(r"[^\w]+", re.UNICODE)
LEADING_SEPARATOR_PATTERN = re.compile(r"^[\s\.\-_、·:：]+")
DOCUMENT_ROOT_ENV = "DOCUMENT_ROOT"
DEFAULT_DOCUMENT_ROOT_NAME = "文稿"
DEFAULT_ARTICLE_PRINCIPLES_DIRNAME = "本地配置"
DEFAULT_ARTICLE_PRINCIPLES_FILENAME = "文章拆解核心原则与心法.md"
SERIES_MAP_EXAMPLE_FILENAME = "series_map.example.json"
YOUTUBE_SOURCES_EXAMPLE_FILENAME = "youtube_sources.example.json"
DEFAULT_AUDIO_DIRS = [
    ("example-series", "示例栏目", "${HOME}/Music/示例栏目"),
]
SERIES_TITLE_PREFIXES = {
    "tiandi": ("天地大道",),
    "human-manual": ("人类说明书", "人類說明書"),
    "human-manual-qa": ("人类说明书问道", "人類說明書問道", "点亮星空问道", "點亮星空問道"),
}


@dataclass(frozen=True)
class TitleIdentity:
    display_title: str
    title_key: str


@dataclass(frozen=True)
class SeriesDefinition:
    key: str
    display_name: str
    audio_dir: Path
    transcript_dir: Path
    prefix_width: int = 2
    title_prefixes: tuple[str, ...] = ()

    def build_title_identity(self, source_name: str) -> TitleIdentity:
        return build_title_identity(self.key, self.display_name, source_name, self.title_prefixes)

    def build_transcript_path(self, source_name: str) -> Path:
        stem = sanitize_filename(Path(source_name).stem)
        return self.transcript_dir / f"{stem}.md"


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
        document_root = resolve_document_root()
        return cls(
            workspace_root=workspace_root,
            manifest_path=workspace_root / ".pipeline" / "manifest.json",
            raw_transcript_dir=workspace_root / ".pipeline" / "raw_transcripts",
            article_dir=document_root / "拆解文章",
            prompts_dir=workspace_root / "prompts",
            series_map_path=workspace_root / ".pipeline" / "series_map.json",
        )


def extract_numeric_prefix(name: str) -> int | None:
    match = NUMERIC_PREFIX_PATTERN.match(name)
    return int(match.group(1)) if match else None


def extract_sequence_prefix(name: str) -> int | None:
    match = NUMERIC_PREFIX_PATTERN.match(name)
    if not match:
        return None
    prefix = match.group(1)
    if len(prefix) == 8 and prefix.startswith("20"):
        return None
    return int(prefix)


def strip_audio_prefix(source_name: str) -> str:
    stem = Path(source_name).stem
    stem = YOUTUBE_ID_SUFFIX_PATTERN.sub("", stem)
    stem = re.sub(r"^\s*\d+\s*[\.\-_、]*\s*", "", stem)
    stem = TITLE_CLEANUP_PATTERN.sub("", stem)
    stem = stem.replace("·", "")
    stem = WHITESPACE_PATTERN.sub(" ", stem).strip()
    return stem or "未命名转录稿"


def sanitize_filename(name: str) -> str:
    sanitized = INVALID_FILENAME_CHARS.sub(" ", name)
    sanitized = WHITESPACE_PATTERN.sub(" ", sanitized).strip()
    return sanitized or "未命名转录稿"


def sanitize_title(title: str) -> str:
    sanitized = TITLE_CLEANUP_PATTERN.sub("", title)
    sanitized = sanitized.replace("/", " ").replace("\\", " ")
    sanitized = sanitized.replace(":", " ").replace("*", " ")
    sanitized = sanitized.replace("?", " ").replace('"', " ")
    sanitized = sanitized.replace("|", " ").replace("·", "")
    sanitized = WHITESPACE_PATTERN.sub(" ", sanitized).strip()
    return sanitized


def resolve_document_root() -> Path:
    configured = os.getenv(DOCUMENT_ROOT_ENV, "").strip()
    if configured:
        return _expand_environment_path(configured)
    return Path.home() / DEFAULT_DOCUMENT_ROOT_NAME


def build_title_identity(
    series_key: str,
    display_name: str,
    source_name: str,
    title_prefixes: Iterable[str] = (),
) -> TitleIdentity:
    title = strip_audio_prefix(source_name)
    title = _strip_series_prefix(title, series_key, display_name, title_prefixes)
    display_title = sanitize_title(title) or "未命名转录稿"
    title_key = build_title_key(display_title)
    return TitleIdentity(display_title=display_title, title_key=title_key)


def build_title_key(display_title: str) -> str:
    normalized = TITLE_KEY_FILTER_PATTERN.sub("", display_title).lower()
    if normalized:
        return normalized
    return hashlib.sha1(display_title.encode("utf-8")).hexdigest()[:16]


def _strip_series_prefix(
    title: str,
    series_key: str,
    display_name: str,
    title_prefixes: Iterable[str] = (),
) -> str:
    prefixes = list(title_prefixes or SERIES_TITLE_PREFIXES.get(series_key, ()))
    prefixes.append(sanitize_title(display_name).replace("-", ""))
    prefixes = [sanitize_title(prefix).replace("-", "") for prefix in prefixes if prefix]
    current = sanitize_title(title)
    for prefix in sorted(set(prefixes), key=len, reverse=True):
        if current.startswith(prefix):
            current = current[len(prefix):]
            current = LEADING_SEPARATOR_PATTERN.sub("", current)
            break
    return current or title


def load_series_map(series_map_path: Path) -> List[SeriesDefinition]:
    data = json.loads(series_map_path.read_text(encoding="utf-8"))
    workspace_root = series_map_path.parent.parent
    series: List[SeriesDefinition] = []
    for item in data.get("series", []):
        audio_dir = _expand_path_value(item["audio_dir"], workspace_root)
        transcript_dir = _expand_path_value(item["transcript_dir"], workspace_root)
        series.append(
            SeriesDefinition(
                key=item["key"],
                display_name=item["display_name"],
                audio_dir=audio_dir,
                transcript_dir=transcript_dir,
                prefix_width=item.get("prefix_width", 2),
                title_prefixes=tuple(item.get("title_prefixes", [])),
            )
        )
    return series


def write_default_series_map(
    series_map_path: Path,
    workspace_root: Path,
    series_audio_dirs: Iterable[tuple[str, str, str]],
) -> None:
    del workspace_root
    payload = {"series": []}
    for key, display_name, audio_dir in series_audio_dirs:
        payload["series"].append(
            {
                "key": key,
                "display_name": display_name,
                "audio_dir": audio_dir,
                "transcript_dir": f"${{{DOCUMENT_ROOT_ENV}}}/录音稿/{display_name}",
                "prefix_width": 2,
                "title_prefixes": [display_name],
            }
        )
    series_map_path.parent.mkdir(parents=True, exist_ok=True)
    series_map_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_local_config(real_path: Path, example_path: Path, writer: Callable[[Path], None]) -> bool:
    if not example_path.exists():
        writer(example_path)
    if real_path.exists():
        return False
    real_path.parent.mkdir(parents=True, exist_ok=True)
    real_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _expand_path_value(value: str, workspace_root: Path) -> Path:
    document_root = resolve_document_root()
    expanded = value.strip()
    replacements = {
        f"${{{DOCUMENT_ROOT_ENV}}}": str(document_root),
        f"${DOCUMENT_ROOT_ENV}": str(document_root),
        "${WORKSPACE_ROOT}": str(workspace_root),
        "$WORKSPACE_ROOT": str(workspace_root),
    }
    for token, replacement in replacements.items():
        expanded = expanded.replace(token, replacement)
    expanded_path = _expand_environment_path(expanded)
    if expanded_path.is_absolute():
        return expanded_path
    return workspace_root / expanded_path


def _expand_environment_path(value: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(value.strip())))


def derive_article_source_dir_name(entry: dict) -> str:
    """Derive a filesystem-safe directory name for article output from a manifest entry."""
    source_name = str(entry.get("source_name") or "")
    if source_name:
        return sanitize_filename(Path(source_name).stem)
    # Fallback: build from sequence + display_title
    sequence = entry.get("sequence")
    if isinstance(sequence, int):
        issue_number = str(sequence).zfill(2)
    elif isinstance(sequence, str) and sequence.isdigit():
        issue_number = sequence.zfill(2)
    else:
        issue_number = "00"
    display_title = sanitize_title(str(entry.get("display_title") or "").strip())
    if not display_title:
        display_title = sanitize_title(strip_audio_prefix(source_name))
    display_title = display_title or "未命名转录稿"
    return f"{issue_number}_{display_title}"


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


def resolve_article_output_dir(base_dir: Path, series_name: str, source_dir_name: str | None = None) -> Path:
    series_dir = base_dir / sanitize_title(series_name)
    if not source_dir_name:
        return series_dir
    return series_dir / sanitize_filename(source_dir_name)


