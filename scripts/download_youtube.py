#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_pipeline.cli_support import filter_series
from audio_pipeline.config import DEFAULT_AUDIO_DIRS, PipelinePaths, load_series_map, write_default_series_map
from audio_pipeline.config import SERIES_MAP_EXAMPLE_FILENAME, YOUTUBE_SOURCES_EXAMPLE_FILENAME, ensure_local_config
from audio_pipeline.task_logging import PipelineTaskLogger
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


def ensure_download_layout(paths: PipelinePaths) -> Path:
    pipeline_dir = paths.series_map_path.parent
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "logs").mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "youtube_archive").mkdir(parents=True, exist_ok=True)
    series_map_example_path = pipeline_dir / SERIES_MAP_EXAMPLE_FILENAME
    ensure_local_config(
        paths.series_map_path,
        series_map_example_path,
        lambda path: write_default_series_map(path, paths.workspace_root, DEFAULT_AUDIO_DIRS),
    )
    youtube_sources_path = pipeline_dir / "youtube_sources.json"
    youtube_sources_example_path = pipeline_dir / YOUTUBE_SOURCES_EXAMPLE_FILENAME
    ensure_local_config(
        youtube_sources_path,
        youtube_sources_example_path,
        lambda path: write_default_youtube_sources(path, load_series_map(paths.series_map_path)),
    )
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
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    logger = PipelineTaskLogger(workspace_root=workspace_root, module="download")
    youtube_sources_path = ensure_download_layout(paths)
    series = filter_series(load_series_map(paths.series_map_path), None if args.all else args.series)
    if not series:
        print("错误：未匹配到任何系列，请检查 --series 参数。")
        logger.finish(status="failed", message="未匹配到任何系列")
        return 2

    sources = load_youtube_sources(youtube_sources_path)
    source_by_key = {item.series_key: item for item in sources}
    selected_sources = [source_by_key[item.key] for item in series if item.key in source_by_key]
    if not selected_sources:
        print(f"错误：{youtube_sources_path} 中没有匹配到任何已配置系列。")
        logger.finish(status="failed", message="youtube_sources.json 中没有匹配到任何已配置系列")
        return 2

    if all(not item.channel_url for item in selected_sources):
        print(f"已准备好配置文件：{youtube_sources_path}")
        print("请先填写每个栏目对应的 YouTube 播放列表或频道 URL，然后重新运行下载脚本。")
        logger.finish(status="skipped", message="未配置任何 channel_url")
        return 0

    downloader = YouTubeBatchDownloader(
        workspace_root=workspace_root,
        ffmpeg_location=resolve_ffmpeg_location(),
        task_logger=logger,
    )
    results = downloader.sync_many(selected_sources, {item.key: item for item in series})
    for series_key, status in results.items():
        print(f"{series_key}: {status}")
    print(f"下载日志：{workspace_root / '.pipeline' / 'logs' / 'youtube_download.log'}")
    success = all(status != "failed" for status in results.values())
    logger.finish(
        status="success" if success else "failed",
        message=f"下载完成，栏目结果：{results}",
    )
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
