from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import PipelinePaths, SeriesDefinition, load_series_map
from .manifest import PipelineManifest
from .migrate_youtube_filenames import migrate_workspace_to_youtube_filenames, resolve_source_name
from .youtube_downloader import load_youtube_sources
from .youtube_naming import (
    build_playlist_source_name_index,
    is_youtube_source_name,
    load_youtube_name_overrides,
    load_youtube_names_from_events,
    lookup_canonical_source_name,
)


@dataclass
class RestoreYoutubeSourceNamesSummary:
    restored_entries: int = 0
    already_canonical: int = 0
    unresolved: int = 0
    migration: dict | None = None
    unresolved_items: list[str] | None = None
    errors: list[str] | None = None


def restore_workspace_youtube_source_names(
    workspace_root: Path,
    *,
    dry_run: bool = False,
    fetch_playlists: bool = True,
) -> RestoreYoutubeSourceNamesSummary:
    workspace_root = workspace_root.resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    series_by_key = {item.key: item for item in load_series_map(paths.series_map_path)}
    manifest = PipelineManifest(paths.manifest_path)
    manifest.load()

    pipeline_dir = paths.workspace_root / ".pipeline"
    events_index = load_youtube_names_from_events(pipeline_dir / "logs" / "events.jsonl")
    overrides_index = load_youtube_name_overrides(pipeline_dir / "youtube_name_overrides.json")
    summary = RestoreYoutubeSourceNamesSummary(unresolved_items=[], errors=[])
    playlist_index_by_series: dict[str, dict[str, str]] = {}
    if fetch_playlists:
        youtube_sources_path = paths.workspace_root / ".pipeline" / "youtube_sources.json"
        if youtube_sources_path.exists():
            for source in load_youtube_sources(youtube_sources_path):
                series = series_by_key.get(source.series_key)
                if series is None or not source.channel_url:
                    continue
                try:
                    playlist_index_by_series[source.series_key] = build_playlist_source_name_index(
                        source.channel_url,
                        series,
                    )
                except Exception as exc:
                    summary.errors.append(f"播放列表拉取失败 {source.series_key}: {exc}")

    for source_id, entry in manifest.entries.items():
        series_key = str(entry.get("series_key") or "")
        series = series_by_key.get(series_key)
        title_key = str(entry.get("title_key") or "")
        if series is None or not title_key:
            summary.unresolved += 1
            summary.unresolved_items.append(source_id)
            continue

        current_name = resolve_source_name(entry)
        if current_name and is_youtube_source_name(current_name):
            summary.already_canonical += 1
            continue

        canonical = lookup_canonical_source_name(
            series_key=series_key,
            title_key=title_key,
            events_index=events_index,
            playlist_index=playlist_index_by_series.get(series_key, {}),
            overrides_index=overrides_index,
        )

        if not canonical:
            summary.unresolved += 1
            summary.unresolved_items.append(source_id)
            continue

        audio_path = series.audio_dir / canonical
        entry["source_name"] = canonical
        entry["source_path"] = str(audio_path)
        summary.restored_entries += 1

    migration_summary = migrate_workspace_to_youtube_filenames(
        workspace_root,
        dry_run=dry_run,
        manifest=manifest,
    )
    if not dry_run and (summary.restored_entries or migration_summary.updated_manifest_entries):
        manifest.save()
    summary.migration = {
        "renamed_transcripts": migration_summary.renamed_transcripts,
        "renamed_raw_transcripts": migration_summary.renamed_raw_transcripts,
        "renamed_article_dirs": migration_summary.renamed_article_dirs,
        "renamed_article_files": migration_summary.renamed_article_files,
        "updated_manifest_entries": migration_summary.updated_manifest_entries,
        "updated_transcript_metadata": migration_summary.updated_transcript_metadata,
        "skipped": migration_summary.skipped,
        "errors": migration_summary.errors or [],
    }
    if migration_summary.errors:
        summary.errors.extend(migration_summary.errors)
    return summary
