#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audio_pipeline.cli_support import filter_series
from audio_pipeline.config import PipelinePaths, load_series_map
from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.pipeline_health import format_transcription_health_message, summarize_transcription_entries
from audio_pipeline.task_logging import PipelineTaskLogger


def _load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="无人值守自动推进音视频下载与 Volcengine ASR 批量转录")
    parser.add_argument("--workspace-root", default=str(ROOT), help="项目根目录，默认仓库根目录")
    parser.add_argument("--series", help="只处理指定系列 key，多个用逗号分隔")
    parser.add_argument("--poll-interval", type=int, default=15, help="转录脚本每轮轮询间隔秒数")
    parser.add_argument("--max-rounds", type=int, default=60, help="转录脚本每轮最多轮询次数")
    parser.add_argument("--max-concurrency", type=int, default=3, help="转录提交并发数")
    parser.add_argument("--max-cycles", type=int, default=12, help="自动驾驶最多跑多少个大循环")
    parser.add_argument("--sleep-seconds", type=int, default=60, help="两轮大循环之间等待秒数")
    parser.add_argument("--max-idle-cycles", type=int, default=2, help="连续多少轮无进展后退出为 incomplete")
    parser.add_argument("--skip-download", action="store_true", help="跳过下载阶段")
    parser.add_argument("--skip-split", action="store_true", help="[已废弃] 下游 LLM 拆稿已移入独立项目 Ordo Scribe")
    parser.add_argument("--expected-articles", type=int, default=None, metavar="N", help="[已废弃] 下游 LLM 拆稿已移入独立项目 Ordo Scribe")
    return parser.parse_args()


def run_step(command: list[str]) -> int:
    result = subprocess.run(command, cwd=str(ROOT), check=False)
    return result.returncode


def count_audio_files(series: list) -> int:
    total = 0
    for item in series:
        if not item.audio_dir.exists():
            continue
        total += sum(
            1
            for path in item.audio_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".mp3" and not path.name.startswith(".")
        )
    return total


def summarize_pipeline(entries: dict, *, series_keys: list[str]) -> dict[str, int | str]:
    report = summarize_transcription_entries(entries, series_keys=series_keys)
    filtered = [entry for entry in entries.values() if not series_keys or entry.get("series_key") in series_keys]
    submitted = sum(1 for entry in filtered if entry.get("job_id") or entry.get("submitted_audio_sha1"))
    failed = sum(
        1
        for entry in filtered
        if entry.get("status") == "failed"
    )
    return {
        "state": report.state,
        "submitted": submitted,
        "completed_transcripts": report.completed_entries,
        "failed": failed,
        "active": report.active_entries,
        "health_message": format_transcription_health_message(report),
    }


def build_cycle_summary(*, cycle: int, new_audio: int, summary: dict[str, int | str]) -> str:
    return (
        f"第 {cycle} 轮：新增音频 {new_audio}，已提交转录任务 {summary['submitted']}，"
        f"已成功转录 {summary['completed_transcripts']}，失败 {summary['failed']}，"
        f"{summary['health_message']}"
    )


def main() -> int:
    _load_env()
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    paths = PipelinePaths.from_workspace(workspace_root)
    manifest = PipelineManifest(paths.manifest_path)
    logger = PipelineTaskLogger(workspace_root=workspace_root, module="autopilot")
    series = filter_series(load_series_map(paths.series_map_path), args.series)
    if not series:
        logger.finish(status="failed", message="未匹配到任何系列")
        return 2

    series_keys = [item.key for item in series]
    python = sys.executable
    idle_cycles = 0
    previous_progress: tuple[int, int, int] | None = None
    total_new_audio = 0

    for cycle in range(1, args.max_cycles + 1):
        logger.log_event(stage="autopilot_cycle", status="started", message=f"开始第 {cycle} 轮", details={"cycle": cycle})
        before_audio = count_audio_files(series)

        if not args.skip_download:
            download_code = run_step(
                [
                    python,
                    "scripts/download_youtube.py",
                    "--workspace-root",
                    str(workspace_root),
                    *(["--series", args.series] if args.series else ["--all"]),
                ]
            )
            if download_code != 0:
                logger.finish(status="failed", message=f"下载阶段失败，退出码 {download_code}")
                return download_code or 2

        after_audio = count_audio_files(series)
        total_new_audio += max(0, after_audio - before_audio)

        transcribe_code = run_step(
            [
                python,
                "scripts/transcribe_batch.py",
                "--workspace-root",
                str(workspace_root),
                "--poll-interval",
                str(args.poll_interval),
                "--max-rounds",
                str(args.max_rounds),
                "--max-concurrency",
                str(args.max_concurrency),
                *(["--series", args.series] if args.series else []),
                "--wait",
            ]
        )
        if transcribe_code not in {0, 3}:
            logger.finish(status="failed", message=f"转录阶段失败，退出码 {transcribe_code}")
            return transcribe_code or 2

        manifest.load()
        summary = summarize_pipeline(manifest.entries, series_keys=series_keys)
        message = build_cycle_summary(cycle=cycle, new_audio=total_new_audio, summary=summary)
        logger.log_event(stage="autopilot_cycle", status="running", message=message, details={"cycle": cycle, **summary})
        print(message)

        if int(summary["failed"]) > 0:
            logger.finish(status="failed", message=message)
            return 2
        if summary["state"] == "all_done":
            logger.finish(status="success", message=message)
            return 0

        progress = (
            int(summary["completed_transcripts"]),
            int(summary["failed"]),
            int(summary["active"]),
        )
        if progress == previous_progress:
            idle_cycles += 1
        else:
            idle_cycles = 0
        previous_progress = progress
        if idle_cycles >= args.max_idle_cycles:
            logger.finish(status="incomplete", message=f"{message}；连续多轮无进展，自动退出。")
            return 3
        if cycle < args.max_cycles:
            time.sleep(args.sleep_seconds)

    logger.finish(status="incomplete", message="达到最大自动驾驶轮次，流程仍未完全收敛。")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
