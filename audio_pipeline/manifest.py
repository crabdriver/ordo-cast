from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .manifest_state import validate_transcription_status_transition


class PipelineManifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: Dict[str, Dict[str, Any]] = {}

    def load(self) -> None:
        if not self.path.exists():
            self.entries = {}
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.entries = payload.get("entries", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": self.entries}
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if not text.strip():
            raise ValueError("manifest 序列化结果为空，拒绝写入")
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(self.path.parent),
            prefix=".manifest-",
            suffix=".tmp",
        ) as tmp:
            tmp.write(text)
            tmp_path = tmp.name
        try:
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get(self, source_id: str) -> Dict[str, Any]:
        entry = self.entries.get(source_id)
        return entry.copy() if entry else {}

    def upsert(self, source_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        current = self.entries.get(source_id, {}).copy()
        if "status" in values:
            validate_transcription_status_transition(current.get("status"), values.get("status"))
        current.update(values)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.entries[source_id] = current
        return current

    def pending_source_ids(self) -> List[str]:
        pending = []
        for source_id, entry in sorted(self.entries.items()):
            if entry.get("status") in {"submitted", "queued", "processing", "retry_pending"}:
                pending.append(source_id)
        return pending
