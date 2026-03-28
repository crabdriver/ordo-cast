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

from audio_pipeline.config import PipelinePaths, load_series_map, write_default_series_map
from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.transcription import AssemblyAITranscriptionProvider
from audio_pipeline.workflow import BatchTranscriptionWorkflow


DEFAULT_AUDIO_DIRS = [
    ("human-manual", "人类说明书", "/Users/wizard/Music/人类说明书"),
    ("human-manual-qa", "人类说明书-问道", "/Users/wizard/Music/人类说明书-问道"),
    ("tiandi", "天地大道", "/Users/wizard/Music/天地大道"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量提交并轮询云端音频转录任务")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument("--poll-interval", type=int, default=15, help="轮询间隔秒数")
    parser.add_argument("--max-rounds", type=int, default=120, help="最大轮询轮次")
    parser.add_argument("--max-concurrency", type=int, default=3, help="并发提交任务数")
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


def build_provider() -> AssemblyAITranscriptionProvider:
    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 ASSEMBLYAI_API_KEY，无法提交云端转录任务。")
    return AssemblyAITranscriptionProvider(api_key=api_key)


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    ensure_workspace_layout(paths)
    series = load_series_map(paths.series_map_path)
    provider = build_provider()
    manifest = PipelineManifest(paths.manifest_path)
    workflow = BatchTranscriptionWorkflow(
        series=series,
        paths=paths,
        manifest=manifest,
        provider=provider,
        max_concurrency=args.max_concurrency,
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
        time.sleep(args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
