#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_pipeline.config import DEFAULT_AUDIO_DIRS, PipelinePaths, load_series_map, write_default_series_map
from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.transcription import AliyunOssSignedUploader, VolcengineBigModelProvider
from audio_pipeline.workflow import BatchTranscriptionWorkflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量提交并轮询云端音频转录任务")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument("--poll-interval", type=int, default=None, help="轮询间隔秒数，不传时按接口模式自动选择")
    parser.add_argument("--max-rounds", type=int, default=120, help="最大轮询轮次")
    parser.add_argument("--max-concurrency", type=int, default=1, help="并发提交任务数")
    parser.add_argument("--api-mode", choices=["standard", "idle"], help="火山接口模式，默认按环境变量或资源 ID 推断")
    parser.add_argument("--series", help="只处理指定系列 key，多个用逗号分隔，例如 tiandi")
    parser.add_argument("--rate-limit-backoff", type=int, default=180, help="遇到 429 后的退避秒数")
    parser.add_argument("--max-submissions-per-run", type=int, default=1, help="每轮最多新提交多少条")
    parser.add_argument("--max-polls-per-run", type=int, default=1, help="每轮最多轮询多少条")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="持续轮询直到全部完成或达到最大轮次",
    )
    return parser.parse_args()


def ensure_workspace_layout(paths: PipelinePaths) -> None:
    paths.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.raw_transcript_dir.mkdir(parents=True, exist_ok=True)
    paths.prompts_dir.mkdir(parents=True, exist_ok=True)
    paths.article_dir.mkdir(parents=True, exist_ok=True)
    if not paths.manifest_path.exists():
        paths.manifest_path.write_text(json.dumps({"entries": {}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not paths.series_map_path.exists():
        write_default_series_map(paths.series_map_path, paths.workspace_root, DEFAULT_AUDIO_DIRS)


def resolve_api_mode(explicit_mode: str | None, resource_id: str | None) -> str:
    if explicit_mode:
        return explicit_mode
    if resource_id and resource_id.endswith("_idle"):
        return "idle"
    return "standard"


def resolve_poll_interval(value: int | None, api_mode: str) -> int:
    if value is not None:
        return value
    if api_mode == "idle":
        return 300
    return 30


def resolve_signed_url_expires(value: str | None, api_mode: str) -> int:
    if value:
        return int(value)
    if api_mode == "idle":
        return 172800
    return 3600


def build_provider(api_mode: str | None = None) -> VolcengineBigModelProvider:
    app_key = os.getenv("VOLCENGINE_APP_KEY")
    access_token = os.getenv("VOLCENGINE_ACCESS_TOKEN")
    configured_resource_id = os.getenv("VOLCENGINE_RESOURCE_ID")
    mode = resolve_api_mode(api_mode or os.getenv("VOLCENGINE_API_MODE"), configured_resource_id)
    default_resource_id = "volc.bigasr.auc_idle" if mode == "idle" else "volc.seedasr.auc"
    resource_id = configured_resource_id or default_resource_id
    oss_access_key_id = os.getenv("OSS_ACCESS_KEY_ID")
    oss_access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
    oss_bucket = os.getenv("OSS_BUCKET")
    oss_endpoint = os.getenv("OSS_ENDPOINT")
    if not all([app_key, access_token, oss_access_key_id, oss_access_key_secret, oss_bucket, oss_endpoint]):
        raise RuntimeError("缺少火山 ASR 或 OSS 环境变量，无法提交云端转录任务。")

    uploader = AliyunOssSignedUploader(
        access_key_id=oss_access_key_id,
        access_key_secret=oss_access_key_secret,
        bucket_name=oss_bucket,
        endpoint=oss_endpoint,
        key_prefix=os.getenv("OSS_AUDIO_PREFIX", "audio-source"),
        expires=resolve_signed_url_expires(os.getenv("OSS_SIGNED_URL_EXPIRES"), mode),
    )
    return VolcengineBigModelProvider(
        app_key=app_key,
        access_key=access_token,
        resource_id=resource_id,
        uploader=uploader.upload,
        api_mode=mode,
    )


def filter_series(series: list, selector: str | None) -> list:
    if not selector:
        return series
    wanted = {item.strip() for item in selector.split(",") if item.strip()}
    return [item for item in series if item.key in wanted or item.display_name in wanted]


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    ensure_workspace_layout(paths)
    try:
        series = filter_series(load_series_map(paths.series_map_path), args.series)
        if not series:
            raise RuntimeError("未匹配到任何系列，请检查 --series 参数。")
        provider = build_provider(args.api_mode)
        poll_interval = resolve_poll_interval(args.poll_interval, provider.api_mode)
        manifest = PipelineManifest(paths.manifest_path)
        workflow = BatchTranscriptionWorkflow(
            series=series,
            paths=paths,
            manifest=manifest,
            provider=provider,
            max_concurrency=args.max_concurrency,
            rate_limit_backoff_seconds=args.rate_limit_backoff,
            max_submissions_per_run=args.max_submissions_per_run,
            max_polls_per_run=args.max_polls_per_run,
        )

        rounds = 0
        while True:
            workflow.run_once()
            manifest.load()
            pending = manifest.pending_source_ids()
            print(f"当前待完成任务数：{len(pending)}")
            if not args.wait or not pending:
                break
            rounds += 1
            if rounds >= args.max_rounds:
                print("达到最大轮询次数，保留当前进度后退出。")
                break
            time.sleep(poll_interval)
        return 0
    except RuntimeError as exc:
        print(f"错误：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
