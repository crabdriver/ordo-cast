#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    manifest_path = ROOT / ".pipeline" / "manifest.json"
    archive_dir = ROOT / ".pipeline" / "youtube_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest_data.get("entries", {})

    # Group completed video IDs by series_key
    completed_ids_by_series = {}
    for key, entry in entries.items():
        if entry.get("status") == "completed":
            series_key = entry.get("series_key")
            source_name = entry.get("source_name") or ""
            
            # Extract YouTube ID e.g. [nhBpIy0Vg5A].mp3 -> nhBpIy0Vg5A
            match = re.search(r"\[([a-zA-Z0-9_-]{11})\]", source_name)
            if match and series_key:
                yt_id = match.group(1)
                completed_ids_by_series.setdefault(series_key, set()).add(yt_id)

    for series_key, ids in completed_ids_by_series.items():
        archive_path = archive_dir / f"{series_key}.txt"
        
        # Read existing archive entries
        existing_ids = set()
        if archive_path.exists():
            for line in archive_path.read_text(encoding="utf-8").splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0] == "youtube":
                    existing_ids.add(parts[1])

        # Merge new ids
        merged_ids = sorted(list(existing_ids.union(ids)))

        # Write back
        new_lines = [f"youtube {yt_id}" for yt_id in merged_ids]
        archive_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"Synced {len(ids)} completed IDs to {archive_path.relative_to(ROOT)} (Total: {len(merged_ids)})")

if __name__ == "__main__":
    main()
