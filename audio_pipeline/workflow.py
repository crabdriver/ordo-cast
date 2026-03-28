from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Iterable

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
    ) -> None:
        self.series = list(series)
        self.paths = paths
        self.manifest = manifest
        self.provider = provider
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries

    def run_once(self) -> None:
        self._ensure_directories()
        self.manifest.load()
        sources = scan_audio_sources(self.series)
        self._submit_pending_sources(sources)
        self.manifest.save()
        for source in sources:
            self._poll_if_needed(source)
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
                    retries = int(current.get("retry_count", 0)) + 1
                    status = "failed" if retries >= self.max_retries else "retry_pending"
                    self.manifest.upsert(
                        source.source_id,
                        {
                            "status": status,
                            "series_key": source.series.key,
                            "source_path": str(source.source_path),
                            "source_name": source.source_path.name,
                            "retry_count": retries,
                            "error_message": str(exc),
                            "raw_transcript_path": str(self._raw_transcript_path(source)),
                            "transcript_path": str(source.transcript_path),
                        },
                    )
                    self.manifest.save()
                    self._log_event(source.source_id, status, str(exc))
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
        retries = int(current.get("retry_count", 0))
        return retries < self.max_retries

    def _poll_if_needed(self, source: AudioSource) -> None:
        current = self.manifest.get(source.source_id)
        if not current.get("job_id"):
            return
        if current.get("status") == "completed":
            return

        try:
            state = self.provider.poll(current["job_id"])
        except Exception as exc:  # pragma: no cover - network failure path
            self.manifest.upsert(
                source.source_id,
                {
                    "status": current.get("status", "submitted") or "submitted",
                    "error_message": str(exc),
                },
            )
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
            status = "failed" if retries >= self.max_retries else "retry_pending"
            self.manifest.upsert(
                source.source_id,
                {
                    "status": status,
                    "job_id": None,
                    "retry_count": retries,
                    "error_message": state.error_message,
                },
            )
            self._log_event(source.source_id, status, state.error_message or "转录失败")
            return

        self.manifest.upsert(
            source.source_id,
            {
                "status": state.status,
                "error_message": None,
            },
        )
        self._log_event(source.source_id, state.status, "轮询中")

    def _raw_transcript_path(self, source: AudioSource) -> Path:
        return self.paths.raw_transcript_dir / source.series.display_name / f"{source.source_path.stem}.txt"

    def _log_path(self) -> Path:
        return self.paths.workspace_root / ".pipeline" / "logs" / "pipeline.log"

    def _log_event(self, source_id: str, status: str, detail: str) -> None:
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {status} | {source_id} | {detail}\n"
        self._log_path().parent.mkdir(parents=True, exist_ok=True)
        with self._log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)

