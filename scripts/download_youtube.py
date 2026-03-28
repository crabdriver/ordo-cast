#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_pipeline.config import DEFAULT_AUDIO_DIRS, PipelinePaths, load_series_map, write_default_series_map
from audio_pipeline.youtube_downloader import (
    YouTubeBatchDownloader,
    load_youtube_sources,
    write_default_youtube_sources,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按栏目同步 YouTube 频道音频到本地 MP3 目录")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument("--series", help="只同步指定系列 key 或 display_name，多个用逗号分隔")
    parser.add_argument("--all", action="store_true", help="同步 youtube_sources.json 中的全部栏目")
    return parser.parse_args()


def filter_series(series: list, selector: str | None) -> list:
    if not selector:
        return series
    wanted = {item.strip() for item in selector.split(",") if item.strip()}
    return [item for item in series if item.key in wanted or item.display_name in wanted]


def ensure_download_layout(paths: PipelinePaths) -> Path:
    pipeline_dir = paths.series_map_path.parent
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "logs").mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "youtube_archive").mkdir(parents=True, exist_ok=True)
    if not paths.series_map_path.exists():
        write_default_series_map(paths.series_map_path, paths.workspace_root, DEFAULT_AUDIO_DIRS)
    youtube_sources_path = pipeline_dir / "youtube_sources.json"
    if not youtube_sources_path.exists():
        write_default_youtube_sources(youtube_sources_path, load_series_map(paths.series_map_path))
    return youtube_sources_path


def resolve_ffmpeg_location() -> Path | None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return Path(ffmpeg_path)
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    return Path(imageio_ffmpeg.get_ffmpeg_exe())


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    youtube_sources_path = ensure_download_layout(paths)
    series = filter_series(load_series_map(paths.series_map_path), None if args.all else args.series)
    if not series:
        print("错误：未匹配到任何系列，请检查 --series 参数。")
        return 2

    sources = load_youtube_sources(youtube_sources_path)
    source_by_key = {item.series_key: item for item in sources}
    selected_sources = [source_by_key[item.key] for item in series if item.key in source_by_key]
    if not selected_sources:
        print(f"错误：{youtube_sources_path} 中没有匹配到任何已配置系列。")
        return 2

    if all(not item.channel_url for item in selected_sources):
        print(f"已准备好配置文件：{youtube_sources_path}")
        print("请先填写每个栏目对应的 YouTube 播放列表或频道 URL，然后重新运行下载脚本。")
        return 0

    downloader = YouTubeBatchDownloader(
        workspace_root=workspace_root,
        ffmpeg_location=resolve_ffmpeg_location(),
    )
    results = downloader.sync_many(selected_sources, {item.key: item for item in series})
    for series_key, status in results.items():
        print(f"{series_key}: {status}")
    print(f"下载日志：{workspace_root / '.pipeline' / 'logs' / 'youtube_download.log'}")
    return 0 if all(status != "failed" for status in results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
