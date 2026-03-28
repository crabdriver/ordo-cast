#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一条命令串联下载与转录流水线")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument("--poll-interval", type=int, default=15, help="转录轮询间隔秒数")
    parser.add_argument("--max-rounds", type=int, default=120, help="转录最大轮询轮次")
    parser.add_argument("--max-concurrency", type=int, default=3, help="并发提交转录任务数")
    parser.add_argument("--wait", action="store_true", help="持续等待到转录任务结束")
    parser.add_argument("--series", help="只处理指定系列 key，多个用逗号分隔")
    parser.add_argument("--skip-download", action="store_true", help="跳过 YouTube 下载阶段")
    parser.add_argument(
        "--auto-split",
        action="store_true",
        help="转录长稿后直接跳过人工复核，继续自动拆成公众号文章",
    )
    return parser.parse_args()


def run_step(command: list[str]) -> None:
    subprocess.run(command, cwd=str(ROOT), check=True)


def main() -> int:
    args = parse_args()
    workspace_root = args.workspace_root
    python = sys.executable

    if not args.skip_download:
        run_step(
            [
                python,
                "scripts/download_youtube.py",
                "--workspace-root",
                workspace_root,
                *(["--series", args.series] if args.series else ["--all"]),
            ]
        )
    run_step(
        [
            python,
            "scripts/transcribe_batch.py",
            "--workspace-root",
            workspace_root,
            "--poll-interval",
            str(args.poll_interval),
            "--max-rounds",
            str(args.max_rounds),
            "--max-concurrency",
            str(args.max_concurrency),
            *(["--series", args.series] if args.series else []),
            *(["--wait"] if args.wait else []),
        ]
    )
    run_step([python, "scripts/normalize_transcript.py", "--workspace-root", workspace_root])
    if args.auto_split:
        run_step(
            [
                python,
                "scripts/split_to_wechat_articles.py",
                "--workspace-root",
                workspace_root,
                "--allow-pending-review",
            ]
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
