#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_pipeline.config import (
    DEFAULT_ARTICLE_PRINCIPLES_DIRNAME,
    DEFAULT_ARTICLE_PRINCIPLES_FILENAME,
    PipelinePaths,
    derive_article_source_dir_name,
    load_series_map,
    resolve_document_root,
    sanitize_title,
)
from audio_pipeline.manifest import PipelineManifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把旧的仓库内文稿迁到新的本地文稿目录结构")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    return parser.parse_args()


def migrate_workspace_layout(workspace_root: Path) -> dict[str, int]:
    workspace_root = workspace_root.resolve()
    document_root = resolve_document_root()
    paths = PipelinePaths.from_workspace(workspace_root)
    summary = {
        "moved_transcripts": 0,
        "moved_articles": 0,
        "copied_principles": 0,
        "moved_legacy_articles": 0,
    }

    series = load_series_map(paths.series_map_path)
    series_by_key = {item.key: item for item in series}
    _rewrite_series_map(paths.series_map_path)

    manifest = PipelineManifest(paths.manifest_path)
    manifest.load()
    for source_id, entry in manifest.entries.items():
        series_item = series_by_key.get(entry.get("series_key"))
        if not series_item:
            continue

        transcript_path = Path(entry.get("transcript_path", ""))
        new_transcript_path = document_root / "录音稿" / sanitize_title(series_item.display_name) / transcript_path.name
        if transcript_path and transcript_path.name:
            if transcript_path.exists():
                if _move_file(transcript_path, new_transcript_path, workspace_root=workspace_root):
                    summary["moved_transcripts"] += 1
            entry["transcript_path"] = str(new_transcript_path)

        article_paths = [Path(path) for path in entry.get("article_paths") or [] if path]
        if article_paths:
            new_article_dir = document_root / "拆解文章" / sanitize_title(series_item.display_name) / derive_article_source_dir_name(entry)
            migrated_paths: list[str] = []
            for article_path in article_paths:
                new_article_path = new_article_dir / article_path.name
                if article_path.exists():
                    if _move_file(article_path, new_article_path, workspace_root=workspace_root):
                        summary["moved_articles"] += 1
                migrated_paths.append(str(new_article_path))
            entry["article_paths"] = migrated_paths

        manifest.entries[source_id] = entry
    manifest.save()

    for item in series:
        legacy_transcript_dir = workspace_root / sanitize_title(item.display_name)
        new_transcript_dir = document_root / "录音稿" / sanitize_title(item.display_name)
        _move_directory_files(legacy_transcript_dir, new_transcript_dir, workspace_root=workspace_root)

    legacy_article_root = workspace_root / "拆解后文章"
    legacy_import_root = document_root / "拆解文章" / "_legacy_flat_import"
    summary["moved_legacy_articles"] += _move_directory_files(legacy_article_root, legacy_import_root, workspace_root=workspace_root)

    legacy_principles_path = workspace_root / "00_文章拆解核心原则与心法.md"
    new_principles_path = document_root / DEFAULT_ARTICLE_PRINCIPLES_DIRNAME / DEFAULT_ARTICLE_PRINCIPLES_FILENAME
    if legacy_principles_path.exists() and not new_principles_path.exists():
        new_principles_path.parent.mkdir(parents=True, exist_ok=True)
        new_principles_path.write_text(legacy_principles_path.read_text(encoding="utf-8"), encoding="utf-8")
        summary["copied_principles"] += 1

    return summary


def _rewrite_series_map(series_map_path: Path) -> None:
    payload = json.loads(series_map_path.read_text(encoding="utf-8"))
    for item in payload.get("series", []):
        display_name = sanitize_title(item["display_name"])
        item["transcript_dir"] = f"${{DOCUMENT_ROOT}}/录音稿/{display_name}"
        audio_dir = item.get("audio_dir", "")
        item["audio_dir"] = _collapse_home(audio_dir)
        item.setdefault("title_prefixes", [item["display_name"]])
    series_map_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _collapse_home(value: str) -> str:
    expanded = Path(os.path.expanduser(os.path.expandvars(value)))
    home = Path.home()
    try:
        relative = expanded.relative_to(home)
    except ValueError:
        return value
    return f"${{HOME}}/{relative.as_posix()}"


def _move_directory_files(source_dir: Path, target_dir: Path, *, workspace_root: Path) -> int:
    if not source_dir.exists() or not source_dir.is_dir():
        return 0
    moved = 0
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        destination = target_dir / path.relative_to(source_dir)
        if _move_file(path, destination, workspace_root=workspace_root):
            moved += 1
    _cleanup_empty_dirs(source_dir, stop_at=workspace_root)
    return moved


def _move_file(source: Path, target: Path, *, workspace_root: Path) -> bool:
    if source.resolve() == target.resolve():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if source.read_bytes() == target.read_bytes():
            source.unlink()
            _cleanup_empty_dirs(source.parent, stop_at=workspace_root)
            return False
        raise FileExistsError(f"迁移目标已存在且内容不同：{target}")
    shutil.move(str(source), str(target))
    _cleanup_empty_dirs(source.parent, stop_at=workspace_root)
    return True


def _cleanup_empty_dirs(path: Path, *, stop_at: Path) -> None:
    stop_resolved = stop_at.resolve()
    current = path.resolve()
    while current.exists() and current.is_dir():
        if current == stop_resolved:
            break
        try:
            current.relative_to(stop_resolved)
        except ValueError:
            break
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def main() -> int:
    args = parse_args()
    summary = migrate_workspace_layout(Path(args.workspace_root))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
