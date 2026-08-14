from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Iterable, List

# 从环境变量读取浏览器名，用于 --cookies-from-browser
# 支持: chrome, firefox, safari, edge, chromium 等
# 留空则不使用 cookies（可能被 YouTube 反爬拦截）
YTDLP_COOKIES_BROWSER = os.environ.get("YTDLP_COOKIES_BROWSER", "chrome")

# 确保 yt-dlp 子进程能找到 Node.js（用于 n-challenge EJS solver）
# macOS 下 Homebrew/nvm/volta 安装的 node 常不在子进程 PATH 里
_NODE_SEARCH_PATHS = [
    "/opt/homebrew/bin",          # Apple Silicon Homebrew
    "/usr/local/bin",             # Intel Homebrew
    str(Path.home() / ".nvm" / "versions" / "node"),  # nvm（通配目录）
    str(Path.home() / ".volta" / "bin"),               # volta
]
_current_path = os.environ.get("PATH", "")
_extra = ":".join(p for p in _NODE_SEARCH_PATHS if p not in _current_path)
if _extra:
    os.environ["PATH"] = _extra + ":" + _current_path

from audio_pipeline.config import SeriesDefinition
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
    workspace_real = str(Path(os.path.realpath(workspace_root))) + os.sep
    for item in data.get("sources", []):
        raw_archive = item["archive_file"]
        archive_file = workspace_root / raw_archive
        real_archive_file = Path(os.path.realpath(archive_file))
        if not str(real_archive_file).startswith(workspace_real):
            raise ValueError(
                f"archive_file 路径超出工作区范围: {real_archive_file}"
            )
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

        cookies_browser = os.environ.get("YTDLP_COOKIES_BROWSER", YTDLP_COOKIES_BROWSER).strip()

        # 显式告知 yt-dlp 使用 node 解 YouTube n-challenge（必须显式传入，否则 _js_runtimes 为空）
        import shutil as _shutil
        _js_runtime_env = os.environ.get("YTDLP_JS_RUNTIME", "").strip()
        if not _js_runtime_env:
            _node_path = _shutil.which("node") or "node"
            _js_runtime_env = f"node:{_node_path}"
        js_runtime_args = ["--js-runtimes", _js_runtime_env]
        
        # Resolve proxy
        proxy_to_use = os.environ.get("YTDLP_PROXY")
        if proxy_to_use is None:
            has_env_proxy = any(
                var in os.environ
                for var in ("all_proxy", "http_proxy", "https_proxy", "ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY")
            )
            if has_env_proxy:
                proxy_to_use = None
            else:
                import socket
                try:
                    with socket.create_connection(("127.0.0.1", 7890), timeout=0.2):
                        proxy_to_use = "http://127.0.0.1:7890"
                except (socket.timeout, ConnectionRefusedError, OSError):
                    proxy_to_use = ""

        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-errors",
            "--no-abort-on-error",
        ]
        if proxy_to_use is not None:
            command.extend(["--proxy", proxy_to_use])

        command.extend([
            *(["--cookies-from-browser", cookies_browser] if cookies_browser else []),
            *js_runtime_args,
            "--concurrent-fragments",
            "5",
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
        ])
        self._log(f"[start] {series.key}: {source.channel_url}")
        self.command_runner(command, self.workspace_root)
        renamed = self._finalize_new_downloads(series, existing_audio_names)
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
            except OSError as exc:
                self._log(f"[error] {series.key}: 文件系统错误 {exc}")
                results[series.key] = "failed"
                continue
            results[series.key] = status
        return results

    def _finalize_new_downloads(self, series: SeriesDefinition, existing_audio_names: set[str]) -> list[Path]:
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

        finalized_targets: list[Path] = []
        for path in new_audio_files:
            title = self._derive_download_title(series, path)
            if title in existing_paths_by_title:
                for existing_path in existing_paths_by_title[title]:
                    if existing_path.exists() and existing_path != path:
                        existing_path.unlink()
                existing_paths_by_title[title] = [path]
                self._log_task(
                    stage="replace_duplicate_audio",
                    status="success",
                    message="用新下载音频替换同标题旧音频",
                    series=series,
                    title_key=series.build_title_identity(path.name).title_key,
                    display_title=title,
                    source_path=str(path),
                )
            else:
                existing_paths_by_title[title] = [path]
            finalized_targets.append(path)
        return finalized_targets

    @staticmethod
    def _derive_download_title(series: SeriesDefinition, path: Path) -> str:
        return series.build_title_identity(path.name).display_title

    @staticmethod
    def _list_audio_names(audio_dir: Path) -> set[str]:
        return {
            path.name
            for path in audio_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".mp3" and not path.name.startswith(".")
        }

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
