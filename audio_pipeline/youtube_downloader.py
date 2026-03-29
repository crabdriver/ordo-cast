from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable, Iterable, List

from audio_pipeline.config import SeriesDefinition, extract_numeric_prefix
from audio_pipeline.task_logging import PipelineTaskLogger


DEFAULT_OUTPUT_TEMPLATE = "%(upload_date>%Y%m%d)s. %(title).180B [%(id)s].%(ext)s"
DEFAULT_DOWNLOAD_MODE = "audio_only_mp3"


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
                "channel_url": "",
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
        task_logger: PipelineTaskLogger | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.command_runner = command_runner or self._run_command
        self.log_path = log_path or workspace_root / ".pipeline" / "logs" / "youtube_download.log"
        self.ffmpeg_location = ffmpeg_location
        self.task_logger = task_logger

    def sync_source(self, source: YouTubeSourceDefinition, series: SeriesDefinition) -> str:
        self._log_task(stage="sync_source", status="started", message="开始同步栏目", series=series)
        if not source.channel_url:
            self._log(f"[skip] {series.key}: 未配置 channel_url，跳过")
            self._log_task(stage="sync_source", status="skipped", message="未配置 channel_url", series=series)
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
            self._log_task(
                stage="download_audio",
                status="success",
                message=f"新增 {len(renamed)} 个音频",
                series=series,
                details={"new_files": [path.name for path in renamed]},
            )
            return "downloaded"
        self._log(f"[done] {series.key}: 没有检测到新视频")
        self._log_task(stage="download_audio", status="success", message="没有检测到新视频", series=series)
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
        existing_audio_paths = {
            path.name: path
            for path in series.audio_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".mp3" and not path.name.startswith(".") and path.name in existing_audio_names
        }
        existing_paths_by_title: dict[str, list[Path]] = {}
        for path in existing_audio_paths.values():
            existing_paths_by_title.setdefault(self._derive_download_title(series, path), []).append(path)
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
            title = self._derive_download_title(series, path)
            if title in existing_paths_by_title:
                target = self._replacement_target(existing_paths_by_title[title])
                for existing_path in existing_paths_by_title[title]:
                    if existing_path.exists():
                        existing_path.unlink()
                path.rename(target)
                renamed_targets.append(target)
                existing_paths_by_title[title] = [target]
                self._log_task(
                    stage="replace_duplicate_audio",
                    status="success",
                    message="用新下载音频替换旧编号音频",
                    series=series,
                    title_key=series.build_title_identity(target.name).title_key,
                    display_title=title,
                    source_path=str(target),
                )
                continue
            target = series.audio_dir / f"{next_sequence:0{series.prefix_width}d}. {title}.mp3"
            path.rename(target)
            renamed_targets.append(target)
            existing_paths_by_title[title] = [target]
            next_sequence += 1
        return renamed_targets

    @staticmethod
    def _derive_download_title(series: SeriesDefinition, path: Path) -> str:
        return series.build_title_identity(path.name).display_title

    @staticmethod
    def _replacement_target(paths: list[Path]) -> Path:
        return sorted(
            paths,
            key=lambda path: (
                extract_numeric_prefix(path.name) is None,
                extract_numeric_prefix(path.name) or 10**9,
                path.name,
            ),
        )[0]

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

    def _log_task(
        self,
        *,
        stage: str,
        status: str,
        message: str,
        series: SeriesDefinition | None = None,
        title_key: str | None = None,
        display_title: str | None = None,
        source_path: str | None = None,
        details: dict | None = None,
    ) -> None:
        if not self.task_logger:
            return
        self.task_logger.log_event(
            stage=stage,
            status=status,
            message=message,
            series_key=series.key if series else None,
            title_key=title_key,
            display_title=display_title,
            source_path=source_path,
            details=details,
        )

    @staticmethod
    def _run_command(command: list[str], cwd: Path) -> None:
        subprocess.run(command, cwd=str(cwd), check=True)
