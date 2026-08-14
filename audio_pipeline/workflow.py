from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from .config import PipelinePaths, SeriesDefinition
from .hashing import sha1_file
from .manifest import PipelineManifest
from .normalization import compute_text_checksum, format_transcript_markdown, scrub_transcript_text
from .scanner import AudioSource, scan_audio_sources
from .task_logging import PipelineTaskLogger
from .transcription import TRANSIENT_ERROR_KEYWORDS, AbstractTranscriptionProvider, TranscriptionJobState


class BatchTranscriptionWorkflow:
    def __init__(
        self,
        *,
        series: Iterable[SeriesDefinition],
        paths: PipelinePaths,
        manifest: PipelineManifest,
        provider: AbstractTranscriptionProvider,
        max_concurrency: int = 3,
        max_retries: int = 3,
        rate_limit_backoff_seconds: int = 180,
        max_submissions_per_run: int | None = 1,
        max_polls_per_run: int | None = 1,
        now_provider: Callable[[], datetime] | None = None,
        task_logger: PipelineTaskLogger | None = None,
    ) -> None:
        self.series = list(series)
        self.paths = paths
        self.manifest = manifest
        self.provider = provider
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.rate_limit_backoff_seconds = rate_limit_backoff_seconds
        self.max_submissions_per_run = max_submissions_per_run
        self.max_polls_per_run = max_polls_per_run
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.task_logger = task_logger
        self._submit_cursor = 0
        self._poll_cursor = 0

    def run_once(self) -> None:
        self._ensure_directories()
        self.manifest.load()
        sources = scan_audio_sources(self.series)
        self._log_task(stage="scan_sources", status="success", message=f"扫描到 {len(sources)} 个音频源", details={"source_count": len(sources)})
        self._reconcile_source_entries(sources)
        sources = self._cleanup_transcribed_sources(sources)
        self._submit_pending_sources(sources)
        self.manifest.save()
        self._poll_due_sources(sources)
        self._cleanup_transcribed_sources(sources)
        self.manifest.save()

    def _ensure_directories(self) -> None:
        self.paths.raw_transcript_dir.mkdir(parents=True, exist_ok=True)
        self.paths.article_dir.mkdir(parents=True, exist_ok=True)
        self.paths.prompts_dir.mkdir(parents=True, exist_ok=True)
        self._log_path().parent.mkdir(parents=True, exist_ok=True)
        for series in self.series:
            series.transcript_dir.mkdir(parents=True, exist_ok=True)

    def _submit_pending_sources(self, sources: Iterable[AudioSource]) -> None:
        pending = [source for source in sources if self._should_submit(source)]
        pending = self._select_batch(
            pending,
            cursor_attr="_submit_cursor",
            limit=self.max_submissions_per_run,
        )
        if not pending:
            return

        with ThreadPoolExecutor(max_workers=max(1, self.max_concurrency)) as executor:
            future_map = {executor.submit(self.provider.submit, source.source_path): source for source in pending}
            for future in as_completed(future_map):
                source = future_map[future]
                current = self.manifest.get(source.source_id)
                try:
                    job_id = future.result()
                except Exception as exc:  # pragma: no cover - network failure path
                    is_retryable = self._is_retryable_submit_error(exc)
                    retries = int(current.get("retry_count", 0))
                    if not is_retryable:
                        retries += 1
                    update = {
                        "status": "retry_pending" if is_retryable else ("failed" if retries >= self.max_retries else "retry_pending"),
                        "series_key": source.series.key,
                        "source_path": str(source.source_path),
                        "source_name": source.source_path.name,
                        "title_key": source.title_key,
                        "display_title": source.title,
                        "audio_sha1": current.get("audio_sha1"),
                        "submitted_audio_sha1": current.get("submitted_audio_sha1"),
                        "retry_count": retries,
                        "error_message": str(exc),
                        "raw_transcript_path": str(self._raw_transcript_path(source)),
                        "transcript_path": str(source.transcript_path),
                    }
                    if is_retryable:
                        update["next_retry_at"] = self._next_retry_timestamp()
                    self.manifest.upsert(source.source_id, update)
                    self.manifest.save()
                    self._log_event(source.source_id, update["status"], str(exc))
                    self._log_task(
                        stage="submit_transcript",
                        status=update["status"],
                        message=str(exc),
                        source=source,
                    )
                    continue

                self.manifest.upsert(
                    source.source_id,
                    {
                        "status": "submitted",
                        "series_key": source.series.key,
                        "source_path": str(source.source_path),
                        "source_name": source.source_path.name,
                        "title_key": source.title_key,
                        "display_title": source.title,
                        "job_id": job_id,
                        "retry_count": int(current.get("retry_count", 0)),
                        "audio_sha1": current.get("audio_sha1"),
                        "submitted_audio_sha1": current.get("audio_sha1"),
                        "raw_transcript_path": str(self._raw_transcript_path(source)),
                        "transcript_path": str(source.transcript_path),
                        "error_message": None,
                        "next_retry_at": None,
                    },
                )
                self.manifest.save()
                self._log_event(source.source_id, "submitted", job_id)
                self._log_task(stage="submit_transcript", status="success", message="已提交火山转录任务", source=source, job_id=job_id)

    def _should_submit(self, source: AudioSource) -> bool:
        current = self.manifest.get(source.source_id)
        if current.get("submitted_audio_sha1") and current.get("submitted_audio_sha1") != current.get("audio_sha1"):
            return True
        if current.get("status") == "completed":
            return False
        if current.get("job_id"):
            return False
        if self._is_waiting_for_retry(current):
            return False
        if current.get("status") == "failed" and not self._is_retryable_submit_error(current.get("error_message")):
            return False
        retries = int(current.get("retry_count", 0))
        if self._is_retryable_submit_error(current.get("error_message")):
            return True
        return retries < self.max_retries

    def _poll_due_sources(self, sources: Iterable[AudioSource]) -> None:
        due = []
        for source in sources:
            current = self.manifest.get(source.source_id)
            if not current.get("job_id"):
                continue
            if current.get("status") == "completed":
                continue
            if self._is_waiting_for_retry(current):
                continue
            due.append(source)
        for source in self._select_batch(due, cursor_attr="_poll_cursor", limit=self.max_polls_per_run):
            self._poll_if_needed(source)

    def _poll_if_needed(self, source: AudioSource) -> None:
        current = self.manifest.get(source.source_id)
        if not self._poll_should_run(current):
            return
        try:
            state = self.provider.poll(current["job_id"])
        except Exception as exc:  # pragma: no cover - network failure path
            self._handle_poll_provider_exception(source, current, exc)
            return
        if state.status == "completed" and state.text is not None:
            self._handle_poll_completed_with_text(source, current, state)
            return
        if state.status == "error":
            self._handle_poll_job_error(source, current, state)
            return
        self._handle_poll_still_running(source, current, state)

    def _poll_should_run(self, current: dict) -> bool:
        if not current.get("job_id"):
            return False
        if current.get("status") == "completed":
            return False
        if self._is_waiting_for_retry(current):
            return False
        return True

    def _handle_poll_provider_exception(self, source: AudioSource, current: dict, exc: Exception) -> None:
        update = {
            "status": current.get("status", "submitted") or "submitted",
            "error_message": str(exc),
        }
        if self._is_rate_limit_error(exc):
            update["next_retry_at"] = self._next_retry_timestamp()
        self.manifest.upsert(source.source_id, update)
        self._log_event(source.source_id, "poll_error", str(exc))
        self._log_task(
            stage="poll_transcript",
            status="retry_pending" if update.get("next_retry_at") else "error",
            message=str(exc),
            source=source,
        )

    def _handle_poll_completed_with_text(self, source: AudioSource, current: dict, state: TranscriptionJobState) -> None:
        try:
            raw_path = Path(current["raw_transcript_path"])
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(state.text or "", encoding="utf-8")

            cleaned = scrub_transcript_text(state.text or "")
            
            # 校验：转录稿字数有效完整性校验（防止因视频下载中途断掉导致录音稿残缺，又将其标为完成）
            if len(cleaned) < source.series.min_transcript_chars:
                raise ValueError(f"转录文字异常过短 (仅 {len(cleaned)} 字)，可能音频不完整或转录损坏，触发重试流程！")

            markdown = format_transcript_markdown(
                series_name=source.series.display_name,
                source_name=source.source_path.name,
                cleaned_text=cleaned,
                reviewed=False,
            )
            source.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            source.transcript_path.write_text(markdown, encoding="utf-8")
            self.manifest.upsert(
                source.source_id,
                {
                    "status": "completed",
                    "raw_transcript_path": str(raw_path),
                    "transcript_path": str(source.transcript_path),
                    "article_status": "pending",
                    "review_status": "pending",
                    "title_key": source.title_key,
                    "display_title": source.title,
                    "audio_sha1": current.get("audio_sha1"),
                    "submitted_audio_sha1": current.get("submitted_audio_sha1") or current.get("audio_sha1"),
                    "transcript_checksum": compute_text_checksum(markdown),
                    "error_message": None,
                    "next_retry_at": None,
                },
            )
            self._log_event(source.source_id, "completed", str(source.transcript_path))
            self._log_task(
                stage="transcript_completed",
                status="success",
                message="已生成转录稿",
                source=source,
                transcript_path=str(source.transcript_path),
                job_id=current.get("job_id"),
            )
        except Exception as exc:
            self.manifest.upsert(
                source.source_id,
                {
                    "status": "failed",
                    "job_id": None,
                    "retry_count": int(current.get("retry_count", 0)) + 1,
                    "error_message": str(exc),
                },
            )
            self._log_event(source.source_id, "failed", str(exc))
            self._log_task(stage="transcript_completed", status="failed", message=str(exc), source=source)

    def _handle_poll_job_error(self, source: AudioSource, current: dict, state: TranscriptionJobState) -> None:
        retries = int(current.get("retry_count", 0)) + 1
        if self._is_rate_limit_error(state.error_message):
            self.manifest.upsert(
                source.source_id,
                {
                    "status": current.get("status", "submitted") or "submitted",
                    "error_message": state.error_message,
                    "next_retry_at": self._next_retry_timestamp(),
                },
            )
            self._log_event(source.source_id, "poll_error", state.error_message or "触发限流")
            self._log_task(stage="poll_transcript", status="retry_pending", message=state.error_message or "触发限流", source=source)
            return
        status = "failed" if retries >= self.max_retries else "retry_pending"
        self.manifest.upsert(
            source.source_id,
            {
                "status": status,
                "job_id": None,
                "retry_count": retries,
                "error_message": state.error_message,
                "next_retry_at": None,
            },
        )
        self._log_event(source.source_id, status, state.error_message or "转录失败")
        self._log_task(stage="poll_transcript", status=status, message=state.error_message or "转录失败", source=source)

    def _handle_poll_still_running(self, source: AudioSource, current: dict, state: TranscriptionJobState) -> None:
        self.manifest.upsert(
            source.source_id,
            {
                "status": state.status,
                "error_message": None,
                "next_retry_at": None,
            },
        )
        self._log_event(source.source_id, state.status, "轮询中")
        self._log_task(stage="poll_transcript", status=state.status, message="轮询中", source=source)

    def _raw_transcript_path(self, source: AudioSource) -> Path:
        return self.paths.raw_transcript_dir / source.series.display_name / f"{source.source_path.stem}.txt"

    def _reconcile_source_entries(self, sources: Iterable[AudioSource]) -> None:
        for source in sources:
            current = self._migrate_legacy_entry(source)
            stored_size = current.get("audio_size")
            stored_mtime = current.get("audio_mtime_ns")
            stored_sha = current.get("audio_sha1")
            if (
                stored_sha
                and isinstance(stored_size, int)
                and isinstance(stored_mtime, int)
                and stored_size == source.audio_size
                and stored_mtime == source.audio_mtime_ns
            ):
                audio_sha1 = stored_sha
            else:
                audio_sha1 = self._audio_sha1(source.source_path)
            transcript_path = self._ensure_transcript_path(source, current)
            update = {
                "series_key": source.series.key,
                "title_key": source.title_key,
                "display_title": source.title,
                "source_path": str(source.source_path),
                "source_name": source.source_path.name,
                "sequence": source.sequence,
                "audio_size": source.audio_size,
                "audio_mtime_ns": source.audio_mtime_ns,
                "audio_sha1": audio_sha1,
                "transcript_path": str(transcript_path),
            }
            if current.get("submitted_audio_sha1") and current.get("submitted_audio_sha1") != audio_sha1:
                update.update(
                    {
                        "status": "pending",
                        "job_id": None,
                        "next_retry_at": None,
                        "error_message": None,
                    }
                )
            self.manifest.upsert(source.source_id, update)

    def _migrate_legacy_entry(self, source: AudioSource) -> dict:
        current = self.manifest.get(source.source_id)
        if current:
            return current
        for key, entry in list(self.manifest.entries.items()):
            if entry.get("series_key") and entry.get("series_key") != source.series.key:
                continue
            if entry.get("title_key") == source.title_key:
                self.manifest.entries.pop(key)
                self.manifest.entries[source.source_id] = entry
                return entry
            legacy_name = entry.get("source_name") or Path(str(entry.get("source_path") or key.split("/", 1)[-1])).name
            if not legacy_name:
                continue
            if source.series.build_title_identity(legacy_name).title_key == source.title_key:
                self.manifest.entries.pop(key)
                self.manifest.entries[source.source_id] = entry
                return entry
        return {}

    def _ensure_transcript_path(self, source: AudioSource, current: dict) -> Path:
        expected_path = source.transcript_path
        current_path_value = current.get("transcript_path")
        if not current_path_value:
            return expected_path
        current_path = Path(current_path_value)
        if current_path == expected_path:
            return expected_path
        if current_path.is_file() and not expected_path.exists():
            expected_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                current_path.rename(expected_path)
            except FileNotFoundError:
                if expected_path.is_file():
                    return expected_path
                if current_path.is_file():
                    return current_path
            return expected_path
        if current_path.is_file():
            return current_path
        return expected_path

    @staticmethod
    def _audio_sha1(path: Path) -> str:
        return sha1_file(path)

    def _cleanup_transcribed_sources(self, sources: Iterable[AudioSource]) -> list[AudioSource]:
        remaining: list[AudioSource] = []
        for source in sources:
            current = self.manifest.get(source.source_id)
            transcript_path = Path(current.get("transcript_path") or source.transcript_path)
            has_active_job = bool(current.get("job_id"))
            has_new_audio_version = bool(current.get("submitted_audio_sha1")) and current.get("submitted_audio_sha1") != current.get("audio_sha1")
            should_delete = not source.series.keep_source and transcript_path.is_file() and not has_new_audio_version and (current.get("status") == "completed" or not has_active_job)
            if not should_delete:
                remaining.append(source)
                continue
            if source.source_path.exists():
                try:
                    source.source_path.unlink()
                    update = {
                        "transcript_path": str(transcript_path),
                        "source_deleted_at": self.now_provider().isoformat(),
                        "source_delete_error": None,
                        "error_message": None,
                    }
                    if not has_active_job:
                        update["status"] = "completed"
                    self.manifest.upsert(source.source_id, update)
                    self._log_event(source.source_id, "source_deleted", str(source.source_path))
                    self._log_task(stage="cleanup_source_audio", status="success", message="已删除已完成转录的源音频", source=source)
                except Exception as exc:
                    self.manifest.upsert(
                        source.source_id,
                        {
                            "source_delete_error": str(exc),
                        },
                    )
                    self._log_event(source.source_id, "source_delete_failed", str(exc))
                    self._log_task(stage="cleanup_source_audio", status="failed", message=str(exc), source=source)
                    remaining.append(source)
            else:
                self.manifest.upsert(
                    source.source_id,
                    {
                        "transcript_path": str(transcript_path),
                        "source_deleted_at": current.get("source_deleted_at") or self.now_provider().isoformat(),
                        "source_delete_error": None,
                    },
                )
        return remaining

    def _log_path(self) -> Path:
        return self.paths.workspace_root / ".pipeline" / "logs" / "pipeline.log"

    def _log_event(self, source_id: str, status: str, detail: str) -> None:
        line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} | {status} | {source_id} | {detail}\n"
        self._log_path().parent.mkdir(parents=True, exist_ok=True)
        with self._log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _log_task(
        self,
        *,
        stage: str,
        status: str,
        message: str,
        source: AudioSource | None = None,
        transcript_path: str | None = None,
        job_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        if not self.task_logger:
            return
        self.task_logger.log_event(
            stage=stage,
            status=status,
            message=message,
            series_key=source.series.key if source else None,
            title_key=source.title_key if source else None,
            display_title=source.title if source else None,
            source_path=str(source.source_path) if source else None,
            transcript_path=transcript_path,
            job_id=job_id,
            details=details,
        )

    def _is_rate_limit_error(self, error: object) -> bool:
        message = str(error)
        return "429" in message or "Too Many Requests" in message

    def _is_transient_network_error(self, error: object) -> bool:
        message = str(error).lower()
        return any(keyword in message for keyword in TRANSIENT_ERROR_KEYWORDS)

    def _is_retryable_submit_error(self, error: object) -> bool:
        return self._is_rate_limit_error(error) or self._is_transient_network_error(error)

    def _next_retry_timestamp(self) -> str:
        return (self.now_provider() + timedelta(seconds=self.rate_limit_backoff_seconds)).isoformat()

    def _is_waiting_for_retry(self, entry: dict) -> bool:
        next_retry_at = entry.get("next_retry_at")
        if not next_retry_at:
            return False
        try:
            return datetime.fromisoformat(next_retry_at) > self.now_provider()
        except ValueError:
            return False

    def _select_batch(
        self,
        items: list[AudioSource],
        *,
        cursor_attr: str,
        limit: int | None,
    ) -> list[AudioSource]:
        if not items or limit is None or limit <= 0 or len(items) <= limit:
            return items
        start = getattr(self, cursor_attr) % len(items)
        ordered = items[start:] + items[:start]
        setattr(self, cursor_attr, (start + limit) % len(items))
        return ordered[:limit]

