#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_pipeline.config import PipelinePaths
from audio_pipeline.manifest import PipelineManifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把长稿标记为已人工复核")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument("--source-id", required=True, help="要标记的 source_id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = PipelinePaths.from_workspace(Path(args.workspace_root).resolve())
    manifest = PipelineManifest(paths.manifest_path)
    manifest.load()
    if args.source_id not in manifest.entries:
        raise RuntimeError(f"未找到 source_id: {args.source_id}")
    entry = manifest.get(args.source_id)
    transcript_path = Path(entry.get("transcript_path", ""))
    if transcript_path.exists():
        content = transcript_path.read_text(encoding="utf-8")
        content = content.replace("状态：待复核", "状态：已复核", 1)
        transcript_path.write_text(content, encoding="utf-8")
    manifest.upsert(
        args.source_id,
        {
            "review_status": "reviewed",
            "article_status": entry.get("article_status", "pending"),
        },
    )
    manifest.save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
