#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experimental_llm_writer.ai_tasks import build_text_client_from_env, llm_cleanup_transcript
from audio_pipeline.config import PipelinePaths, load_series_map
from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.normalization import (
    build_normalization_manifest_update,
    compute_text_checksum,
    format_transcript_markdown,
    should_skip_normalization,
)
from audio_pipeline.task_logging import PipelineTaskLogger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把原始转录缓存整理成长稿 Markdown")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument("--source-id", default=None, help="只处理指定 source_id")
    parser.add_argument("--series", help="只处理指定系列 key，多个用逗号分隔")
    parser.add_argument("--force", action="store_true", help="即使已人工复核也强制重写长稿")
    return parser.parse_args()


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    manifest = PipelineManifest(paths.manifest_path)
    manifest.load()
    series_index = {series.key: series for series in load_series_map(paths.series_map_path)}
    client = build_text_client_from_env()
    if client is None:
        print(
            "提示：未配置 CONTENT_LLM_API_KEY / CONTENT_LLM_BASE_URL / CONTENT_LLM_MODEL，将仅使用规则清洗（无 LLM 润色）。",
            flush=True,
        )
    prompt_path = Path(__file__).parent / "prompts" / "clean_transcript.md"
    selected_series = {item.strip() for item in (args.series or "").split(",") if item.strip()}
    logger = PipelineTaskLogger(workspace_root=workspace_root, module="normalize")
    failure_count = 0

    for source_id, entry in manifest.entries.items():
        if args.source_id and source_id != args.source_id:
            continue
        if selected_series and entry.get("series_key") not in selected_series:
            continue
        raw_path = Path(entry.get("raw_transcript_path", ""))
        transcript_path = Path(entry.get("transcript_path", ""))
        if not raw_path.exists() or not transcript_path:
            continue
        try:
            existing_text = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else None
            if should_skip_normalization(existing_text=existing_text, entry=entry, force=args.force):
                manifest.upsert(
                    source_id,
                    {
                        "normalization_status": entry.get("normalization_status", "skipped"),
                        "normalization_error": None,
                    },
                )
                logger.log_event(
                    stage="normalize_transcript",
                    status="skipped",
                    message="检测到人工修改或已完成规范化，跳过",
                    series_key=entry.get("series_key"),
                    title_key=entry.get("title_key"),
                    display_title=entry.get("display_title"),
                    transcript_path=str(transcript_path),
                )
                continue
            series = series_index[entry["series_key"]]
            raw_text = raw_path.read_text(encoding="utf-8")
            cleaned = llm_cleanup_transcript(
                client=client,
                prompt_path=prompt_path,
                series_name=series.display_name,
                source_name=entry["source_name"],
                raw_transcript=raw_text,
            )
            markdown = format_transcript_markdown(
                series_name=series.display_name,
                source_name=entry["source_name"],
                cleaned_text=cleaned,
                reviewed=False,
            )
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            transcript_path.write_text(markdown, encoding="utf-8")
            update = build_normalization_manifest_update(previous_entry=entry, markdown=markdown)
            update["transcript_path"] = str(transcript_path)
            update["transcript_checksum"] = compute_text_checksum(markdown)
            manifest.upsert(source_id, update)
            logger.log_event(
                stage="normalize_transcript",
                status="success",
                message="已完成长稿规范化",
                series_key=entry.get("series_key"),
                title_key=entry.get("title_key"),
                display_title=entry.get("display_title"),
                transcript_path=str(transcript_path),
            )
        except Exception as exc:
            manifest.upsert(
                source_id,
                {
                    "normalization_status": "failed",
                    "normalization_error": str(exc),
                },
            )
            logger.log_event(
                stage="normalize_transcript",
                status="failed",
                message=str(exc),
                series_key=entry.get("series_key"),
                title_key=entry.get("title_key"),
                display_title=entry.get("display_title"),
                transcript_path=str(transcript_path),
            )
            failure_count += 1

    manifest.save()
    logger.finish(
        status="failed" if failure_count else "success",
        message=f"规范化结束，失败 {failure_count} 条",
    )
    return 2 if failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
