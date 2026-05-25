#!/usr/bin/env python3
"""Extract audio (mp3) from mp4 video files into a target directory.

Usage:
    python scripts/extract_mp4_audio.py \
        --source "/path/to/videos" \
        --target "/path/to/audio_out"

Already-extracted files are skipped (idempotent).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def default_jobs() -> int:
    cpu = os.cpu_count() or 4
    return max(1, min(8, cpu // 2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 mp4 视频文件提取 mp3 音频")
    parser.add_argument("--source", required=True, help="源视频文件夹路径")
    parser.add_argument("--target", required=True, help="输出 mp3 文件夹路径")
    parser.add_argument("--audio-quality", default="2", help="mp3 VBR 质量 (0=最高, 9=最低), 默认 2")
    parser.add_argument(
        "--jobs",
        type=int,
        default=default_jobs(),
        help=f"并行转码数，默认 {default_jobs()}（按 CPU 核数估算）",
    )
    parser.add_argument(
        "--threads-per-job",
        type=int,
        default=2,
        help="每个 ffmpeg 进程使用的线程数，默认 2",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="更快模式：质量降为 4，适合语音转录",
    )
    return parser.parse_args()


def extract_audio(src: Path, dst: Path, quality: str, threads_per_job: int) -> bool:
    """Extract audio from src (mp4) to dst (mp3). Returns True on success."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        str(max(1, threads_per_job)),
        "-i",
        str(src),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-q:a",
        quality,
        "-y",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [错误] ffmpeg 退出码 {result.returncode}:", file=sys.stderr)
        print(result.stderr[-2000:], file=sys.stderr)
        return False
    return True


def main() -> int:
    args = parse_args()
    source_dir = Path(args.source).expanduser().resolve()
    target_dir = Path(args.target).expanduser().resolve()

    if not source_dir.exists():
        print(f"[错误] 源文件夹不存在: {source_dir}", file=sys.stderr)
        return 1

    target_dir.mkdir(parents=True, exist_ok=True)

    mp4_files = sorted(
        [p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"],
        key=lambda p: p.name,
    )

    if not mp4_files:
        print(f"[警告] 未在 {source_dir} 找到 mp4 文件")
        return 0

    quality = "4" if args.fast else args.audio_quality
    pending: list[tuple[int, Path, Path]] = []
    skipped = 0
    for idx, src in enumerate(mp4_files, 1):
        dst = target_dir / (src.stem + ".mp3")
        if dst.exists():
            print(f"[{idx}/{len(mp4_files)}] 跳过（已存在）: {dst.name}")
            skipped += 1
            continue
        pending.append((idx, src, dst))

    print(
        f"共发现 {len(mp4_files)} 个 mp4，待转 {len(pending)} 个，"
        f"并行 {max(1, args.jobs)}，质量 q:a={quality}，目标: {target_dir}"
    )
    ok = 0
    failed = 0

    def run_one(item: tuple[int, Path, Path]) -> tuple[int, Path, Path, bool]:
        idx, src, dst = item
        print(f"[{idx}/{len(mp4_files)}] 提取中: {src.name} -> {dst.name}")
        success = extract_audio(src, dst, quality, args.threads_per_job)
        return idx, src, dst, success

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as executor:
            futures = [executor.submit(run_one, item) for item in pending]
            for future in as_completed(futures):
                idx, src, dst, success = future.result()
                if success:
                    print(f"  ✓ [{idx}/{len(mp4_files)}] 完成 {dst.name} ({dst.stat().st_size // 1024 // 1024} MB)")
                    ok += 1
                else:
                    print(f"  ✗ [{idx}/{len(mp4_files)}] 失败 {src.name}", file=sys.stderr)
                    failed += 1

    print(f"\n完成: 成功 {ok}，跳过 {skipped}，失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
