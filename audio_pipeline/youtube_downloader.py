from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Iterable, List

from audio_pipeline.config import SeriesDefinition, extract_numeric_prefix, sanitize_title


DEFAULT_OUTPUT_TEMPLATE = "%(upload_date>%Y%m%d)s. %(title).180B [%(id)s].%(ext)s"
DEFAULT_DOWNLOAD_MODE = "audio_only_mp3"
DOWNLOAD_ID_SUFFIX_PATTERN = re.compile(r"\s+\[[^\]]+\]$")
DEFAULT_YOUTUBE_SOURCE_URLS = {
    "tiandi": "https://www.youtube.com/playlist?list=PLwUkfFsdDFqkqU28gZ3he1VWIR5wgAC1E",
    "human-manual": "https://www.youtube.com/playlist?list=PLwUkfFsdDFqmbqFpcO1NR8cdqp0HhFpuO",
    "human-manual-qa": "https://www.youtube.com/playlist?list=PLwUkfFsdDFqllxE2T7qkaLodYU1igH0kb",
}


@dataclass(frozen=True)
class YouTubeSourceDefinition:
    series_key: str
    channel_url: str
    download_mode: str
    archive_file: Path


def load_youtube_sources(config_path: Path) -> List[YouTubeSourceDefinition]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    workspace_root = config_path.parent.parent
    sources: List[YouTubeSourceDefinition] = []
    for item in data.get("sources", []):
        archive_file = Path(item["archive_file"])
        if not archive_file.is_absolute():
            archive_file = workspace_root / archive_file
        sources.append(
            YouTubeSourceDefinition(
                series_key=item["series_key"],
                channel_url=item.get("channel_url", "").strip(),
                download_mode=item.get("download_mode", DEFAULT_DOWNLOAD_MODE),
                archive_file=archive_file,
            )
        )
    return sources


def write_default_youtube_sources(config_path: Path, series: Iterable[SeriesDefinition]) -> None:
    payload = {"sources": []}
    for item in series:
        payload["sources"].append(
            {
                "series_key": item.key,
                "channel_url": DEFAULT_YOUTUBE_SOURCE_URLS.get(item.key, ""),
                "download_mode": DEFAULT_DOWNLOAD_MODE,
                "archive_file": f".pipeline/youtube_archive/{item.key}.txt",
            }
        )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class YouTubeBatchDownloader:
    def __init__(
        self,
        workspace_root: Path,
        *,
        command_runner: Callable[[list[str], Path], None] | None = None,
        log_path: Path | None = None,
        ffmpeg_location: Path | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.command_runner = command_runner or self._run_command
        self.log_path = log_path or workspace_root / ".pipeline" / "logs" / "youtube_download.log"
        self.ffmpeg_location = ffmpeg_location

    def sync_source(self, source: YouTubeSourceDefinition, series: SeriesDefinition) -> str:
        if not source.channel_url:
            self._log(f"[skip] {series.key}: 未配置 channel_url，跳过")
            return "skipped"
        if source.download_mode != DEFAULT_DOWNLOAD_MODE:
            raise RuntimeError(f"暂不支持下载模式：{source.download_mode}")

        series.audio_dir.mkdir(parents=True, exist_ok=True)
        source.archive_file.parent.mkdir(parents=True, exist_ok=True)
        existing_audio_names = self._list_audio_names(series.audio_dir)

        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-errors",
            "--no-abort-on-error",
            "--extractor-args",
            "youtube:player_client=android",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            *(["--ffmpeg-location", str(self.ffmpeg_location)] if self.ffmpeg_location else []),
            "--download-archive",
            str(source.archive_file),
            "--output",
            DEFAULT_OUTPUT_TEMPLATE,
            "--paths",
            str(series.audio_dir),
            source.channel_url,
        ]
        self._log(f"[start] {series.key}: {source.channel_url}")
        self.command_runner(command, self.workspace_root)
        renamed = self._rename_new_downloads(series, existing_audio_names)
        if renamed:
            self._log(f"[done] {series.key}: 新增 {len(renamed)} 个音频 -> {series.audio_dir}")
            return "downloaded"
        self._log(f"[done] {series.key}: 没有检测到新视频")
        return "unchanged"

    def sync_many(
        self,
        sources: Iterable[YouTubeSourceDefinition],
        series_by_key: dict[str, SeriesDefinition],
    ) -> dict[str, str]:
        results: dict[str, str] = {}
        for source in sources:
            series = series_by_key.get(source.series_key)
            if series is None:
                raise RuntimeError(f"youtube_sources.json 中的 series_key 不存在：{source.series_key}")
            try:
                status = self.sync_source(source, series)
            except subprocess.CalledProcessError as exc:
                self._log(f"[error] {series.key}: 下载失败，退出码 {exc.returncode}")
                results[series.key] = "failed"
                continue
            results[series.key] = status
        return results

    def _rename_new_downloads(self, series: SeriesDefinition, existing_audio_names: set[str]) -> list[Path]:
        existing_titles = {self._derive_download_title(Path(name)) for name in existing_audio_names}
        new_audio_files = sorted(
            [
                path
                for path in series.audio_dir.iterdir()
                if path.is_file() and path.suffix.lower() == ".mp3" and not path.name.startswith(".") and path.name not in existing_audio_names
            ],
            key=lambda path: path.name,
        )
        if not new_audio_files:
            return []

        next_sequence = self._next_sequence(existing_audio_names)
        renamed_targets: list[Path] = []
        for path in new_audio_files:
            title = self._derive_download_title(path)
            if title in existing_titles:
                path.unlink(missing_ok=True)
                continue
            target = series.audio_dir / f"{next_sequence:0{series.prefix_width}d}. {title}.mp3"
            path.rename(target)
            renamed_targets.append(target)
            existing_titles.add(title)
            next_sequence += 1
        return renamed_targets

    def _derive_download_title(self, path: Path) -> str:
        stem = DOWNLOAD_ID_SUFFIX_PATTERN.sub("", path.stem)
        stem = re.sub(r"^\s*\d+\s*[\.\-_、]*\s*", "", stem)
        title = sanitize_title(stem)
        return title or "未命名音频"

    @staticmethod
    def _list_audio_names(audio_dir: Path) -> set[str]:
        return {
            path.name
            for path in audio_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".mp3" and not path.name.startswith(".")
        }

    @staticmethod
    def _next_sequence(existing_audio_names: set[str]) -> int:
        numbered = [extract_numeric_prefix(name) for name in existing_audio_names]
        numeric_values = [value for value in numbered if value is not None]
        if numeric_values:
            return max(numeric_values) + 1
        return len(existing_audio_names) + 1

    def _log(self, message: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    @staticmethod
    def _run_command(command: list[str], cwd: Path) -> None:
        subprocess.run(command, cwd=str(cwd), check=True)
