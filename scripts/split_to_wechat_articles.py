#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_pipeline.ai_tasks import build_text_client_from_env, llm_generate_articles
from audio_pipeline.article_splitter import (
    resolve_article_output_dir,
    should_generate_articles,
    write_articles,
)
from audio_pipeline.config import PipelinePaths, load_series_map
from audio_pipeline.manifest import PipelineManifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把长稿拆成适合公众号发布的文章")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument("--source-id", default=None, help="只处理指定 source_id")
    parser.add_argument(
        "--allow-pending-review",
        action="store_true",
        help="即使长稿还未人工复核，也直接生成公众号文章",
    )
    return parser.parse_args()


def derive_issue_number(source_name: str) -> str:
    prefix = source_name.split(".", 1)[0].strip()
    return prefix.zfill(2) if prefix.isdigit() else prefix


def extract_transcript_body(transcript_text: str) -> str:
    marker = "\n---\n\n"
    if marker in transcript_text:
        return transcript_text.split(marker, 1)[1].strip()
    return transcript_text.strip()


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    manifest = PipelineManifest(paths.manifest_path)
    manifest.load()
    series_index = {series.key: series for series in load_series_map(paths.series_map_path)}
    client = build_text_client_from_env()
    if client is None:
        raise RuntimeError("缺少 CONTENT_LLM_API_KEY / BASE_URL / MODEL，无法拆稿。")

    prompt_path = paths.prompts_dir / "split_wechat_articles.md"
    for source_id, entry in manifest.entries.items():
        if args.source_id and source_id != args.source_id:
            continue
        if not should_generate_articles(entry, allow_pending_review=args.allow_pending_review):
            continue
        transcript_path = Path(entry["transcript_path"])
        if not transcript_path.exists():
            continue
        try:
            transcript_text = extract_transcript_body(transcript_path.read_text(encoding="utf-8"))
            issue_number = derive_issue_number(entry["source_name"])
            drafts = llm_generate_articles(
                client=client,
                prompt_path=prompt_path,
                issue_number=issue_number,
                transcript_text=transcript_text,
            )
            series = series_index[entry["series_key"]]
            output_dir = resolve_article_output_dir(paths.article_dir, series.display_name)
            article_paths = write_articles(output_dir, issue_number, drafts)
            manifest.upsert(
                source_id,
                {
                    "article_status": "completed",
                    "article_paths": [str(path) for path in article_paths],
                    "article_error": None,
                },
            )
        except Exception as exc:
            manifest.upsert(
                source_id,
                {
                    "article_status": "failed",
                    "article_error": str(exc),
                },
            )

    manifest.save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
