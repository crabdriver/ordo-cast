from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


ACTIVE_TRANSCRIPTION_STATUSES = frozenset({"pending", "submitted", "queued", "processing", "retry_pending"})


@dataclass(frozen=True)
class TranscriptionHealthReport:
    state: str
    total_entries: int
    completed_entries: int
    active_entries: int
    failed_entries: int
    status_counts: dict[str, int]


def summarize_transcription_entries(
    entries: Mapping[str, Mapping[str, Any]],
    *,
    series_keys: Iterable[str] | None = None,
) -> TranscriptionHealthReport:
    wanted = set(series_keys or [])
    counts: Counter[str] = Counter()
    total_entries = 0
    for entry in entries.values():
        if wanted and entry.get("series_key") not in wanted:
            continue
        total_entries += 1
        counts[str(entry.get("status") or "")] += 1

    active_entries = sum(count for status, count in counts.items() if status in ACTIVE_TRANSCRIPTION_STATUSES)
    completed_entries = counts.get("completed", 0)
    failed_entries = counts.get("failed", 0)
    if failed_entries:
        state = "failed"
    elif active_entries:
        state = "incomplete"
    else:
        state = "all_done"
    return TranscriptionHealthReport(
        state=state,
        total_entries=total_entries,
        completed_entries=completed_entries,
        active_entries=active_entries,
        failed_entries=failed_entries,
        status_counts=dict(counts),
    )


def format_transcription_health_message(report: TranscriptionHealthReport) -> str:
    return (
        f"状态={report.state}，总条目={report.total_entries}，"
        f"已完成={report.completed_entries}，进行中/待重试={report.active_entries}，失败={report.failed_entries}"
    )
