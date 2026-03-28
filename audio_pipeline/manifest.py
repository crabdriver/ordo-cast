from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List


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
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def get(self, source_id: str) -> Dict[str, Any]:
        return self.entries.get(source_id, {})

    def upsert(self, source_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        current = self.entries.get(source_id, {}).copy()
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

