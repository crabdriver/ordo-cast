#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_pipeline.migrate_youtube_filenames import migrate_workspace_to_youtube_filenames


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把历史录音稿与拆稿目录重命名为 YouTube 源音频同名")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览变更，不实际移动文件或写 manifest",
    )
    return parser.parse_args()


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    args = parse_args()
    summary = migrate_workspace_to_youtube_filenames(Path(args.workspace_root), dry_run=args.dry_run)
    payload = {
        "renamed_transcripts": summary.renamed_transcripts,
        "renamed_raw_transcripts": summary.renamed_raw_transcripts,
        "renamed_article_dirs": summary.renamed_article_dirs,
        "renamed_article_files": summary.renamed_article_files,
        "updated_manifest_entries": summary.updated_manifest_entries,
        "updated_transcript_metadata": summary.updated_transcript_metadata,
        "deleted_orphan_raw_transcripts": summary.deleted_orphan_raw_transcripts,
        "skipped": summary.skipped,
        "errors": summary.errors or [],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if payload["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
