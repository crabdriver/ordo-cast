#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from subprocess import CalledProcessError

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一条命令串联下载、转录、规范化与拆稿流水线")
    parser.add_argument(
        "--workspace-root",
        default=str(ROOT),
        help="项目根目录，默认是当前仓库根目录",
    )
    parser.add_argument("--poll-interval", type=int, default=15, help="转录轮询间隔秒数")
    parser.add_argument("--max-rounds", type=int, default=120, help="转录最大轮询轮次")
    parser.add_argument("--max-concurrency", type=int, default=3, help="并发提交转录任务数")
    parser.add_argument("--wait", action="store_true", help="兼容旧参数；总控默认会等待转录完成")
    parser.add_argument("--series", help="只处理指定系列 key，多个用逗号分隔")
    parser.add_argument("--skip-download", action="store_true", help="跳过 YouTube 下载阶段")
    parser.add_argument("--skip-split", action="store_true", help="跳过自动拆稿阶段")
    parser.add_argument(
        "--allow-pending-review",
        action="store_true",
        help="拆稿阶段允许「待复核」长稿（传给 split_to_wechat_articles）",
    )
    parser.add_argument(
        "--expected-articles",
        type=int,
        default=None,
        metavar="N",
        help="拆稿输出必须恰好 N 篇（传给 split_to_wechat_articles；也可在 .env 设 EXPECTED_ARTICLES_PER_TRANSCRIPT）",
    )
    return parser.parse_args()


def run_step(label: str, command: list[str]) -> None:
    try:
        subprocess.run(command, cwd=str(ROOT), check=True)
    except CalledProcessError as exc:
        print(f"步骤「{label}」失败，退出码 {exc.returncode}。")
        raise


def main() -> int:
    _load_env()
    args = parse_args()
    workspace_root = args.workspace_root
    python = sys.executable

    try:
        if not args.skip_download:
            run_step(
                "YouTube 下载",
                [
                    python,
                    "scripts/download_youtube.py",
                    "--workspace-root",
                    workspace_root,
                    *(["--series", args.series] if args.series else ["--all"]),
                ],
            )
        run_step(
            "批量转录",
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
                "--wait",
            ],
        )
        run_step(
            "转录稿规范化",
            [
                python,
                "scripts/normalize_transcript.py",
                "--workspace-root",
                workspace_root,
                *(["--series", args.series] if args.series else []),
            ],
        )
        if not args.skip_split:
            split_cmd = [
                python,
                "scripts/split_to_wechat_articles.py",
                "--workspace-root",
                workspace_root,
                *(["--series", args.series] if args.series else []),
            ]
            if args.allow_pending_review:
                split_cmd.append("--allow-pending-review")
            if args.expected_articles is not None:
                split_cmd.extend(["--expected-articles", str(args.expected_articles)])
            run_step("公众号拆稿", split_cmd)
    except CalledProcessError as exc:
        return exc.returncode if exc.returncode else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
