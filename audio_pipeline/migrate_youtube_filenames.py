from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .article_splitter import derive_article_source_dir_name, derive_issue_number_from_entry, resolve_article_output_dir
from .config import PipelinePaths, SeriesDefinition, build_title_key, load_series_map, sanitize_filename, sanitize_title
from .manifest import PipelineManifest
from .normalization import compute_text_checksum


ARTICLE_FILE_PATTERN = re.compile(r"^(\d+)-(\d{2})_(.+)$")
LEGACY_DIR_PREFIX_PATTERN = re.compile(r"^\d{8}_|^\d+_")
LEGACY_NUMBERED_FILE_PATTERN = re.compile(r"^\d{1,2}\.\s")
TRANSCRIPT_SOURCE_LINE_PATTERN = re.compile(r"^原音频：.*$", re.MULTILINE)


@dataclass
class MigrationSummary:
    renamed_transcripts: int = 0
    renamed_raw_transcripts: int = 0
    renamed_article_dirs: int = 0
    renamed_article_files: int = 0
    updated_manifest_entries: int = 0
    updated_transcript_metadata: int = 0
    deleted_orphan_raw_transcripts: int = 0
    skipped: int = 0
    errors: list[str] | None = None


def resolve_source_name(entry: dict) -> str:
    source_name = str(entry.get("source_name") or "").strip()
    if source_name:
        return source_name
    source_path = str(entry.get("source_path") or "").strip()
    if source_path:
        return Path(source_path).name
    return ""


def migrate_workspace_to_youtube_filenames(
    workspace_root: Path,
    *,
    dry_run: bool = False,
    manifest: PipelineManifest | None = None,
) -> MigrationSummary:
    workspace_root = workspace_root.resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    series_by_key = {item.key: item for item in load_series_map(paths.series_map_path)}
    active_manifest = manifest or PipelineManifest(paths.manifest_path)
    if manifest is None:
        active_manifest.load()

    summary = MigrationSummary(errors=[])
    for source_id, entry in list(active_manifest.entries.items()):
        series_key = entry.get("series_key")
        series = series_by_key.get(series_key or "")
        if series is None:
            summary.skipped += 1
            continue

        source_name = resolve_source_name(entry)
        if not source_name:
            summary.skipped += 1
            continue

        changed = False
        try:
            if _migrate_transcript(entry, series, summary=summary, dry_run=dry_run):
                changed = True
            if _update_transcript_source_name_metadata(entry, series, summary=summary, dry_run=dry_run):
                changed = True
            if _migrate_raw_transcript(entry, paths, series, summary=summary, dry_run=dry_run):
                changed = True
            if _migrate_articles(entry, paths, series, summary=summary, dry_run=dry_run):
                changed = True
        except Exception as exc:
            summary.errors.append(f"{source_id}: {exc}")
            continue

        if changed:
            active_manifest.entries[source_id] = entry
            summary.updated_manifest_entries += 1

    if not dry_run and summary.updated_manifest_entries:
        active_manifest.save()

    try:
        summary.deleted_orphan_raw_transcripts = cleanup_orphan_numbered_raw_transcripts(
            paths.raw_transcript_dir,
            dry_run=dry_run,
        )
    except Exception as exc:
        summary.errors.append(f"cleanup_orphan_raw_transcripts: {exc}")

    return summary


def _migrate_transcript(entry: dict, series: SeriesDefinition, *, summary: MigrationSummary, dry_run: bool) -> bool:
    expected = series.build_transcript_path(resolve_source_name(entry))
    current_value = str(entry.get("transcript_path") or "").strip()
    current = Path(current_value) if current_value else expected
    if current == expected:
        if current_value != str(expected):
            entry["transcript_path"] = str(expected)
            return True
        return False

    if not current.exists():
        entry["transcript_path"] = str(expected)
        return current_value != str(expected)

    if expected.exists() and current != expected:
        _move_path(current, expected, dry_run=dry_run, prefer_target_on_conflict=True)
        entry["transcript_path"] = str(expected)
        if current != expected:
            summary.renamed_transcripts += 1
        return True

    _move_path(current, expected, dry_run=dry_run)
    entry["transcript_path"] = str(expected)
    summary.renamed_transcripts += 1
    return True


def _update_transcript_source_name_metadata(
    entry: dict,
    series: SeriesDefinition,
    *,
    summary: MigrationSummary,
    dry_run: bool,
) -> bool:
    source_name = resolve_source_name(entry)
    if not source_name:
        return False

    transcript_value = str(entry.get("transcript_path") or "").strip()
    transcript_path = (
        Path(transcript_value)
        if transcript_value
        else series.build_transcript_path(source_name)
    )
    if not transcript_path.exists():
        return False

    content = transcript_path.read_text(encoding="utf-8")
    if "原音频：" not in content:
        return False

    expected_line = f"原音频：{source_name}"
    updated, count = TRANSCRIPT_SOURCE_LINE_PATTERN.subn(expected_line, content, count=1)
    if count == 0 or updated == content:
        return False

    if not dry_run:
        transcript_path.write_text(updated, encoding="utf-8")
        entry["transcript_checksum"] = compute_text_checksum(updated)
        if str(entry.get("transcript_path") or "") != str(transcript_path):
            entry["transcript_path"] = str(transcript_path)

    summary.updated_transcript_metadata += 1
    return True


def _migrate_raw_transcript(
    entry: dict,
    paths: PipelinePaths,
    series: SeriesDefinition,
    *,
    summary: MigrationSummary,
    dry_run: bool,
) -> bool:
    source_name = resolve_source_name(entry)
    expected = paths.raw_transcript_dir / series.display_name / f"{sanitize_filename(Path(source_name).stem)}.txt"
    current_value = str(entry.get("raw_transcript_path") or "").strip()
    current = Path(current_value) if current_value else expected
    if current == expected:
        if not current.exists():
            legacy = _find_legacy_numbered_raw_transcript(expected.parent, source_name)
            if legacy is not None:
                _move_path(legacy, expected, dry_run=dry_run)
                entry["raw_transcript_path"] = str(expected)
                summary.renamed_raw_transcripts += 1
                return True
        if current_value != str(expected):
            entry["raw_transcript_path"] = str(expected)
            return True
        return False

    if not current.exists():
        legacy = _find_legacy_numbered_raw_transcript(expected.parent, source_name)
        if legacy is not None:
            current = legacy

    if not current.exists():
        entry["raw_transcript_path"] = str(expected)
        return current_value != str(expected)

    if expected.exists() and current != expected:
        _move_path(current, expected, dry_run=dry_run, prefer_target_on_conflict=True)
        entry["raw_transcript_path"] = str(expected)
        if current != expected:
            summary.renamed_raw_transcripts += 1
        return True

    _move_path(current, expected, dry_run=dry_run)
    entry["raw_transcript_path"] = str(expected)
    summary.renamed_raw_transcripts += 1
    return True


def _migrate_articles(
    entry: dict,
    paths: PipelinePaths,
    series: SeriesDefinition,
    *,
    summary: MigrationSummary,
    dry_run: bool,
) -> bool:
    new_issue = derive_issue_number_from_entry(entry)
    new_dir_name = derive_article_source_dir_name(entry)
    new_dir = resolve_article_output_dir(paths.article_dir, series.display_name, new_dir_name)
    old_dir = _find_legacy_article_dir(paths.article_dir, series, entry, exclude=new_dir_name)
    changed = False

    article_paths = [Path(path) for path in entry.get("article_paths") or [] if path]
    if old_dir is None and article_paths:
        old_dir = article_paths[0].parent if article_paths[0].parent.exists() else None

    if old_dir is not None and old_dir != new_dir:
        if new_dir.exists() and any(new_dir.iterdir()) and old_dir.exists():
            raise FileExistsError(f"目标文章目录已存在且非空：{new_dir}")
        if old_dir.exists():
            if dry_run:
                summary.renamed_article_dirs += 1
            else:
                new_dir.parent.mkdir(parents=True, exist_ok=True)
                if new_dir.exists():
                    shutil.rmtree(new_dir)
                old_dir.rename(new_dir)
                summary.renamed_article_dirs += 1
            changed = True
        article_paths = [new_dir / path.name for path in article_paths]

    if new_dir.exists():
        migrated_paths: list[str] = []
        for path in sorted(new_dir.glob("*.md")):
            match = ARTICLE_FILE_PATTERN.match(path.name)
            if not match:
                migrated_paths.append(str(path))
                continue
            old_issue, index, title_part = match.groups()
            if old_issue == new_issue:
                migrated_paths.append(str(path))
                continue
            target = new_dir / f"{new_issue}-{index}_{title_part}"
            _move_path(path, target, dry_run=dry_run)
            migrated_paths.append(str(target))
            summary.renamed_article_files += 1
            changed = True
        if migrated_paths:
            entry["article_paths"] = migrated_paths
            changed = True
    elif article_paths:
        entry["article_paths"] = [str(path) for path in article_paths]
        changed = True

    return changed


def _find_legacy_article_dir(
    article_root: Path,
    series: SeriesDefinition,
    entry: dict,
    *,
    exclude: str,
) -> Path | None:
    series_root = article_root / sanitize_title(series.display_name)
    if not series_root.exists():
        return None

    title_key = str(entry.get("title_key") or "")
    matches: list[Path] = []
    for path in series_root.iterdir():
        if not path.is_dir() or path.name == exclude:
            continue
        if _legacy_dir_matches_entry(path.name, title_key, entry):
            matches.append(path)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return max(matches, key=lambda item: item.stat().st_mtime_ns)

    display_title = sanitize_title(str(entry.get("display_title") or ""))
    sequence = entry.get("sequence")
    legacy_names: list[str] = []
    if isinstance(sequence, int):
        legacy_names.extend(
            [
                f"{sequence:02d}_{display_title}",
                f"{sequence}_{display_title}",
            ]
        )
    for name in legacy_names:
        candidate = series_root / name
        if candidate.exists():
            return candidate
    return None


def _legacy_dir_matches_entry(dir_name: str, title_key: str, entry: dict) -> bool:
    if not title_key:
        return False
    body = LEGACY_DIR_PREFIX_PATTERN.sub("", dir_name, count=1)
    body = sanitize_title(body)
    if build_title_key(body) == title_key:
        return True
    display_title = sanitize_title(str(entry.get("display_title") or ""))
    return body == display_title


def _find_legacy_numbered_raw_transcript(series_dir: Path, source_name: str) -> Path | None:
    if not series_dir.exists():
        return None
    matches: list[Path] = []
    youtube_stem = Path(source_name).stem
    for path in series_dir.glob("*.txt"):
        if not LEGACY_NUMBERED_FILE_PATTERN.match(path.name):
            continue
        numbered_title = LEGACY_NUMBERED_FILE_PATTERN.sub("", path.stem)
        if _numbered_title_matches_youtube(numbered_title, youtube_stem):
            matches.append(path)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return max(matches, key=lambda item: item.stat().st_mtime_ns)
    return None


def cleanup_orphan_numbered_raw_transcripts(raw_transcript_dir: Path, *, dry_run: bool) -> int:
    deleted = 0
    if not raw_transcript_dir.exists():
        return deleted

    for series_dir in raw_transcript_dir.iterdir():
        if not series_dir.is_dir():
            continue
        youtube_files = [
            path
            for path in series_dir.glob("*.txt")
            if " [" in path.name and path.name.endswith("].txt")
        ]
        if not youtube_files:
            continue
        for numbered in series_dir.glob("*.txt"):
            if not LEGACY_NUMBERED_FILE_PATTERN.match(numbered.name):
                continue
            numbered_title = LEGACY_NUMBERED_FILE_PATTERN.sub("", numbered.stem)
            if not any(_numbered_title_matches_youtube(numbered_title, youtube.stem) for youtube in youtube_files):
                continue
            if not dry_run:
                numbered.unlink()
            deleted += 1
    return deleted


def _numbered_title_matches_youtube(numbered_title: str, youtube_stem: str) -> bool:
    left = sanitize_title(numbered_title)
    body = re.sub(r" \[[^\]]+\]$", "", youtube_stem)
    body = re.sub(r"^\d{8}\.\s*", "", body)
    right = sanitize_title(body)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _move_path(source: Path, target: Path, *, dry_run: bool, prefer_target_on_conflict: bool = False) -> None:
    if source.resolve() == target.resolve():
        return
    if target.exists():
        if source.read_bytes() == target.read_bytes():
            if not dry_run:
                source.unlink()
            return
        if prefer_target_on_conflict:
            if not dry_run:
                source.unlink()
            return
        raise FileExistsError(f"迁移目标已存在且内容不同：{target}")
    if dry_run:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
