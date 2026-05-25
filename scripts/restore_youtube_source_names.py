#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_pipeline.restore_youtube_source_names import restore_workspace_youtube_source_names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把 manifest 中被重编号的 source_name 恢复为 YouTube 原名，并重命名录音稿")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览变更，不实际写 manifest 或移动文件",
    )
    parser.add_argument(
        "--skip-playlist-fetch",
        action="store_true",
        help="不拉取 YouTube 播放列表，仅使用 events.jsonl 中的历史记录",
    )
    return parser.parse_args()


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    args = parse_args()
    summary = restore_workspace_youtube_source_names(
        Path(args.workspace_root),
        dry_run=args.dry_run,
        fetch_playlists=not args.skip_playlist_fetch,
    )
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    if summary.errors or summary.unresolved:
        return 2 if summary.errors else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
