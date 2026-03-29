from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PipelineTaskLogger:
    workspace_root: Path
    module: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self) -> None:
        self.logs_dir = self.workspace_root / ".pipeline" / "logs"
        self.runs_dir = self.logs_dir / "runs"
        self.events_path = self.logs_dir / "events.jsonl"
        self.latest_status_path = self.logs_dir / "latest_status.json"
        self.summary_path = self.runs_dir / f"{self.run_id}.summary.json"
        self.started_at = _utc_now()
        self.event_counts: dict[str, int] = {}
        self._ensure_dirs()
        self._write_summary(status="running", message=None)
        self._write_latest_status(status="running", message=None)

    def log_event(
        self,
        *,
        stage: str,
        status: str,
        message: str,
        series_key: str | None = None,
        title_key: str | None = None,
        display_title: str | None = None,
        source_path: str | None = None,
        transcript_path: str | None = None,
        job_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "timestamp": _utc_now(),
            "run_id": self.run_id,
            "module": self.module,
            "stage": stage,
            "status": status,
            "message": message,
            "series_key": series_key,
            "title_key": title_key,
            "display_title": display_title,
            "source_path": source_path,
            "transcript_path": transcript_path,
            "job_id": job_id,
            "details": details or {},
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.event_counts[f"{stage}.{status}"] = self.event_counts.get(f"{stage}.{status}", 0) + 1
        self._write_summary(status="running", message=message, last_event=event)
        self._write_latest_status(status="running", message=message, last_event=event)

    def finish(self, *, status: str, message: str | None = None) -> None:
        finished_at = _utc_now()
        self._write_summary(status=status, message=message, finished_at=finished_at)
        self._write_latest_status(status=status, message=message, finished_at=finished_at)

    def _ensure_dirs(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _write_summary(
        self,
        *,
        status: str,
        message: str | None,
        finished_at: str | None = None,
        last_event: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "run_id": self.run_id,
            "module": self.module,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "status": status,
            "message": message,
            "event_counts": self.event_counts,
            "last_event": last_event,
        }
        self.summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _write_latest_status(
        self,
        *,
        status: str,
        message: str | None,
        finished_at: str | None = None,
        last_event: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "run_id": self.run_id,
            "module": self.module,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "status": status,
            "message": message,
            "last_event": last_event,
        }
        self.latest_status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
