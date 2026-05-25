#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from subprocess import CalledProcessError

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一条命令串联下载与 Volcano ASR 转录流水线")
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
    parser.add_argument("--skip-split", action="store_true", help="[已废弃] 下游 LLM 拆稿已移入 experimental_llm_writer")
    parser.add_argument(
        "--full-auto",
        action="store_true",
        help="[已废弃] 全自动模式已移入 experimental_llm_writer",
    )
    parser.add_argument(
        "--allow-pending-review",
        action="store_true",
        help="[已废弃] 拆稿阶段已移入 experimental_llm_writer",
    )
    parser.add_argument(
        "--expected-articles",
        type=int,
        default=None,
        metavar="N",
        help="[已废弃] 拆稿篇数参数已移入 experimental_llm_writer",
    )
    return parser.parse_args()


def resolve_full_auto(explicit: bool) -> bool:
    if explicit:
        return True
    raw = os.getenv("PIPELINE_FULL_AUTO", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def run_step(label: str, command: list[str]) -> None:
    try:
        subprocess.run(command, cwd=str(ROOT), check=True)
    except CalledProcessError as exc:
        suffix = "（任务未收敛，请继续轮询或检查失败条目）" if exc.returncode == 3 else ""
        print(f"步骤「{label}」失败，退出码 {exc.returncode}。{suffix}")
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
        
        print("\n" + "="*60)
        print("🎉 核心音视频下载与高精度 ASR 语音转录已成功完成！")
        print("生成的 Markdown 录音稿已保存在您的文稿目录中。")
        print("="*60)
        print("💡 提示：实验性的 LLM 长稿润色与微信公众号拆稿功能已独立剥离。")
        print("若需要运行它们，请移步子项目目录进行操作：")
        print("  python3 experimental_llm_writer/normalize_transcript.py")
        print("  python3 experimental_llm_writer/split_to_wechat_articles.py")
        print("="*60 + "\n")
    except CalledProcessError as exc:
        return exc.returncode if exc.returncode else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
