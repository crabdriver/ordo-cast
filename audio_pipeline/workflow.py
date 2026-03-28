from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from .config import PipelinePaths, SeriesDefinition
from .manifest import PipelineManifest
from .normalization import compute_text_checksum, format_transcript_markdown, scrub_transcript_text
from .scanner import AudioSource, scan_audio_sources
from .transcription import AbstractTranscriptionProvider


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
        self._submit_cursor = 0
        self._poll_cursor = 0

    def run_once(self) -> None:
        self._ensure_directories()
        self.manifest.load()
        sources = self._cleanup_transcribed_sources(scan_audio_sources(self.series))
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
                    continue

                self.manifest.upsert(
                    source.source_id,
                    {
                        "status": "submitted",
                        "series_key": source.series.key,
                        "source_path": str(source.source_path),
                        "source_name": source.source_path.name,
                        "job_id": job_id,
                        "retry_count": int(current.get("retry_count", 0)),
                        "raw_transcript_path": str(self._raw_transcript_path(source)),
                        "transcript_path": str(source.transcript_path),
                        "error_message": None,
                        "next_retry_at": None,
                    },
                )
                self.manifest.save()
                self._log_event(source.source_id, "submitted", job_id)

    def _should_submit(self, source: AudioSource) -> bool:
        current = self.manifest.get(source.source_id)
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
        if not current.get("job_id"):
            return
        if current.get("status") == "completed":
            return
        if self._is_waiting_for_retry(current):
            return

        try:
            state = self.provider.poll(current["job_id"])
        except Exception as exc:  # pragma: no cover - network failure path
            update = {
                "status": current.get("status", "submitted") or "submitted",
                "error_message": str(exc),
            }
            if self._is_rate_limit_error(exc):
                update["next_retry_at"] = self._next_retry_timestamp()
            self.manifest.upsert(source.source_id, update)
            self._log_event(source.source_id, "poll_error", str(exc))
            return
        if state.status == "completed" and state.text is not None:
            try:
                raw_path = Path(current["raw_transcript_path"])
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(state.text, encoding="utf-8")

                cleaned = scrub_transcript_text(state.text)
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
                        "transcript_checksum": compute_text_checksum(markdown),
                        "error_message": None,
                        "next_retry_at": None,
                    },
                )
                self._log_event(source.source_id, "completed", str(source.transcript_path))
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
            return

        if state.status == "error":
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
            return

        self.manifest.upsert(
            source.source_id,
            {
                "status": state.status,
                "error_message": None,
                "next_retry_at": None,
            },
        )
        self._log_event(source.source_id, state.status, "轮询中")

    def _raw_transcript_path(self, source: AudioSource) -> Path:
        return self.paths.raw_transcript_dir / source.series.display_name / f"{source.source_path.stem}.txt"

    def _cleanup_transcribed_sources(self, sources: Iterable[AudioSource]) -> list[AudioSource]:
        remaining: list[AudioSource] = []
        for source in sources:
            current = self.manifest.get(source.source_id)
            transcript_path = Path(current.get("transcript_path") or source.transcript_path)
            has_active_job = bool(current.get("job_id"))
            should_delete = transcript_path.is_file() and (current.get("status") == "completed" or not has_active_job)
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
                except Exception as exc:
                    self.manifest.upsert(
                        source.source_id,
                        {
                            "source_delete_error": str(exc),
                        },
                    )
                    self._log_event(source.source_id, "source_delete_failed", str(exc))
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
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {status} | {source_id} | {detail}\n"
        self._log_path().parent.mkdir(parents=True, exist_ok=True)
        with self._log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _is_rate_limit_error(self, error: object) -> bool:
        message = str(error)
        return "429" in message or "Too Many Requests" in message

    def _is_transient_network_error(self, error: object) -> bool:
        message = str(error).lower()
        return any(
            keyword in message
            for keyword in (
                "connection reset by peer",
                "connection aborted",
                "requesterror",
                "timed out",
                "temporarily unavailable",
                "eof occurred in violation of protocol",
            )
        )

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

