#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experimental_llm_writer.ai_tasks import build_text_client_from_env, llm_generate_articles
from experimental_llm_writer.article_splitter import (
    derive_article_source_dir_name,
    derive_issue_number_from_entry,
    inspect_article_output_state,
    list_issue_article_files,
    resolve_article_output_dir,
    should_generate_articles,
    validate_article_drafts,
    write_articles,
)
from audio_pipeline.config import PipelinePaths, load_series_map, resolve_article_principles_path
from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.task_logging import PipelineTaskLogger

MAX_ARTICLE_GENERATION_ATTEMPTS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把长稿拆成适合公众号发布的文章")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument("--source-id", default=None, help="只处理指定 source_id")
    parser.add_argument("--series", help="只处理指定系列 key，多个用逗号分隔")
    parser.add_argument(
        "--allow-pending-review",
        action="store_true",
        help="长稿在 manifest 中仍为「待复核」(review_status=pending) 时也拆稿；默认跳过待复核条目",
    )
    parser.add_argument(
        "--expected-articles",
        type=int,
        default=None,
        metavar="N",
        help="拆稿输出篇数必须恰好为 N（与 LLM 返回的 articles 数量一致）；"
        "未传参时可读环境变量 EXPECTED_ARTICLES_PER_TRANSCRIPT",
    )
    return parser.parse_args()


def resolve_expected_article_count(args: argparse.Namespace) -> int | None:
    if args.expected_articles is not None:
        if args.expected_articles < 1:
            print("错误：--expected-articles 必须为正整数。", file=sys.stderr)
            raise SystemExit(2)
        return args.expected_articles
    raw = os.environ.get("EXPECTED_ARTICLES_PER_TRANSCRIPT", "").strip()
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        print("错误：环境变量 EXPECTED_ARTICLES_PER_TRANSCRIPT 必须为正整数。", file=sys.stderr)
        raise SystemExit(2)
    if n < 1:
        print("错误：环境变量 EXPECTED_ARTICLES_PER_TRANSCRIPT 必须为正整数。", file=sys.stderr)
        raise SystemExit(2)
    return n


def extract_transcript_body(transcript_text: str) -> str:
    marker = "\n---\n\n"
    if marker in transcript_text:
        return transcript_text.split(marker, 1)[1].strip()
    return transcript_text.strip()


def archive_existing_output_dir(*, output_dir: Path, archive_root: Path) -> Path | None:
    if not output_dir.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    archive_dir = archive_root / timestamp / output_dir.relative_to(output_dir.parent.parent)
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(output_dir), str(archive_dir))
    return archive_dir


def generate_articles_with_retry(
    *,
    client,
    prompt_path: Path,
    issue_number: str,
    transcript_text: str,
    principles_text: str,
    expected_article_count: int | None,
    logger: PipelineTaskLogger,
    entry: dict,
) -> list:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ARTICLE_GENERATION_ATTEMPTS + 1):
        try:
            drafts = llm_generate_articles(
                client=client,
                prompt_path=prompt_path,
                issue_number=issue_number,
                transcript_text=transcript_text,
                principles_text=principles_text,
                expected_article_count=expected_article_count,
            )
            return validate_article_drafts(drafts, expected_count=expected_article_count)
        except Exception as exc:
            last_exc = exc
            if attempt >= MAX_ARTICLE_GENERATION_ATTEMPTS:
                break
            logger.log_event(
                stage="split_articles_retry",
                status="retrying",
                message=f"第 {attempt} 次拆稿失败，准备重试：{exc}",
                series_key=entry.get("series_key"),
                title_key=entry.get("title_key"),
                display_title=entry.get("display_title"),
                transcript_path=entry.get("transcript_path"),
                details={"attempt": attempt},
            )
    raise RuntimeError(f"拆稿连续 {MAX_ARTICLE_GENERATION_ATTEMPTS} 次失败：{last_exc}")


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    args = parse_args()
    expected_article_count = resolve_expected_article_count(args)
    workspace_root = Path(args.workspace_root).resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    manifest = PipelineManifest(paths.manifest_path)
    manifest.load()
    series_index = {series.key: series for series in load_series_map(paths.series_map_path)}
    logger = PipelineTaskLogger(workspace_root=workspace_root, module="split")
    client = None
    prompt_path = Path(__file__).parent / "prompts" / "split_wechat_articles.md"
    principles_path = resolve_article_principles_path()
    if not principles_path.exists():
        message = f"缺少拆稿原则文件：{principles_path}"
        logger.finish(status="failed", message=message)
        return 2
    principles_text = principles_path.read_text(encoding="utf-8")
    failure_count = 0
    selected_series = {item.strip() for item in (args.series or "").split(",") if item.strip()}
    article_archive_root = workspace_root / ".pipeline" / "recovery" / "articles"
    for source_id, entry in manifest.entries.items():
        if args.source_id and source_id != args.source_id:
            continue
        if selected_series and entry.get("series_key") not in selected_series:
            continue
        output_state = inspect_article_output_state(entry)
        if output_state == "all_present":
            if entry.get("article_status") != "completed":
                manifest.upsert(
                    source_id,
                    {
                        "article_status": "completed",
                        "article_error": None,
                    },
                )
                logger.log_event(
                    stage="repair_article_state",
                    status="success",
                    message="检测到文章文件已齐全，已修复 manifest 状态",
                    series_key=entry.get("series_key"),
                    title_key=entry.get("title_key"),
                    display_title=entry.get("display_title"),
                    transcript_path=entry.get("transcript_path"),
                )
            continue
        if not should_generate_articles(entry, allow_pending_review=args.allow_pending_review):
            continue
        series = series_index[entry["series_key"]]
        issue_number = derive_issue_number_from_entry(entry)
        output_dir = resolve_article_output_dir(
            paths.article_dir,
            series.display_name,
            derive_article_source_dir_name(entry),
        )
        disk_article_paths = list_issue_article_files(output_dir, issue_number)
        if output_state == "partial":
            archive_dir = archive_existing_output_dir(output_dir=output_dir, archive_root=article_archive_root)
            manifest.upsert(
                source_id,
                {
                    "article_status": "pending",
                    "article_paths": [],
                    "article_error": None,
                    "article_archive_dir": str(archive_dir) if archive_dir else entry.get("article_archive_dir"),
                },
            )
            logger.log_event(
                stage="repair_article_state",
                status="success",
                message="检测到部分文章文件，已自动归档并准备重试拆稿",
                series_key=entry.get("series_key"),
                title_key=entry.get("title_key"),
                display_title=entry.get("display_title"),
                transcript_path=entry.get("transcript_path"),
                details={
                    "article_paths": entry.get("article_paths", []),
                    "archive_dir": str(archive_dir) if archive_dir else None,
                },
            )
        elif not entry.get("article_paths") and disk_article_paths:
            archive_dir = archive_existing_output_dir(output_dir=output_dir, archive_root=article_archive_root)
            manifest.upsert(
                source_id,
                {
                    "article_status": "pending",
                    "article_paths": [],
                    "article_error": None,
                    "article_archive_dir": str(archive_dir) if archive_dir else entry.get("article_archive_dir"),
                },
            )
            logger.log_event(
                stage="repair_article_state",
                status="success",
                message="检测到磁盘上残留旧文章目录，已自动归档并准备重试拆稿",
                series_key=entry.get("series_key"),
                title_key=entry.get("title_key"),
                display_title=entry.get("display_title"),
                transcript_path=entry.get("transcript_path"),
                details={
                    "disk_article_paths": [str(path) for path in disk_article_paths],
                    "archive_dir": str(archive_dir) if archive_dir else None,
                },
            )
        transcript_path = Path(entry["transcript_path"])
        if not transcript_path.exists():
            message = f"转录稿不存在：{transcript_path}"
            manifest.upsert(
                source_id,
                {
                    "article_status": "failed",
                    "article_error": message,
                },
            )
            logger.log_event(
                stage="split_articles",
                status="failed",
                message=message,
                series_key=entry.get("series_key"),
                title_key=entry.get("title_key"),
                display_title=entry.get("display_title"),
                transcript_path=str(transcript_path),
            )
            failure_count += 1
            continue
        try:
            if client is None:
                client = build_text_client_from_env()
            if client is None:
                raise RuntimeError("缺少 CONTENT_LLM_API_KEY / BASE_URL / MODEL，无法拆稿。")
            transcript_text = extract_transcript_body(transcript_path.read_text(encoding="utf-8"))
            drafts = generate_articles_with_retry(
                client=client,
                prompt_path=prompt_path,
                issue_number=issue_number,
                transcript_text=transcript_text,
                principles_text=principles_text,
                expected_article_count=expected_article_count,
                logger=logger,
                entry=entry,
            )
            article_paths = write_articles(output_dir, issue_number, drafts)
            manifest.upsert(
                source_id,
                {
                    "article_status": "completed",
                    "article_paths": [str(path) for path in article_paths],
                    "article_error": None,
                },
            )
            logger.log_event(
                stage="split_articles",
                status="success",
                message=f"已生成 {len(article_paths)} 篇文章",
                series_key=entry.get("series_key"),
                title_key=entry.get("title_key"),
                display_title=entry.get("display_title"),
                transcript_path=str(transcript_path),
                details={"article_paths": [str(path) for path in article_paths]},
            )
        except Exception as exc:
            manifest.upsert(
                source_id,
                {
                    "article_status": "failed",
                    "article_error": str(exc),
                },
            )
            logger.log_event(
                stage="split_articles",
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
        message=f"拆稿结束，失败 {failure_count} 条",
    )
    return 2 if failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
