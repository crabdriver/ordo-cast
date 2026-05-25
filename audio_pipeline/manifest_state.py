"""转录流水线 manifest 顶层 `status` 字段的非法跳转校验（最小集）。"""

from __future__ import annotations

from enum import Enum
from typing import Final


class TranscriptionStatus(str, Enum):
    """manifest.entries[*].status 的已知取值（字符串与枚举成员名一致）。"""

    PENDING = "pending"
    SUBMITTED = "submitted"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY_PENDING = "retry_pending"


KNOWN_TRANSCRIPTION_STATUSES: Final[frozenset[str]] = frozenset(s.value for s in TranscriptionStatus)

# 明显非法：已完成或已失败却直接跳到「进行中」类状态，或失败直接变完成（须先 reconcile / 重提）
_FORBIDDEN: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("completed", "submitted"),
        ("completed", "queued"),
        ("completed", "processing"),
        ("completed", "retry_pending"),
        ("failed", "completed"),
        ("failed", "queued"),
        ("failed", "processing"),
    }
)


def validate_transcription_status_transition(old: str | None, new: str | None) -> None:
    """
    在 upsert 写入新 status 前调用。仅校验「旧→新」组合；首次写入（无旧 status）不限制。

    Raises:
        ValueError: 命中禁止跳转表。
    """
    if new is None or not isinstance(new, str):
        return
    old_key = old if isinstance(old, str) and old.strip() else None
    if old_key is None:
        return
    pair = (old_key, new)
    if pair in _FORBIDDEN:
        raise ValueError(
            f"manifest status 非法跳转: {old_key!r} -> {new!r}。"
            "已完成条目须先经 pending（如音频变更 reconcile），"
            "失败条目不能直接变为 completed/queued/processing。"
        )
