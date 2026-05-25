from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest
from unittest.mock import patch

from audio_pipeline.config import PipelinePaths, SeriesDefinition, load_series_map
from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.scanner import scan_audio_sources


class ScannerAndManifestTests(unittest.TestCase):
    def test_scan_audio_sources_maps_series_and_groups_same_title_by_stable_key(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio_root = root / "audio"
            output_root = root / "output"
            (audio_root / "天地大道").mkdir(parents=True)
            (audio_root / "人类说明书").mkdir(parents=True)
            output_root.mkdir()

            (audio_root / "天地大道" / "02. 第二讲.mp3").write_bytes(b"b")
            (audio_root / "天地大道" / "01. 第一讲.mp3").write_bytes(b"a")
            (audio_root / "天地大道" / ".DS_Store").write_text("", encoding="utf-8")
            (audio_root / "人类说明书" / "3. 「人類說明書」关系底牌.mp3").write_bytes(b"c")
            (audio_root / "人类说明书" / "20260328. 「人類說明書」关系底牌 [abc123].mp3").write_bytes(b"d")

            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=audio_root / "天地大道",
                    transcript_dir=output_root / "天地大道",
                    prefix_width=2,
                ),
                SeriesDefinition(
                    key="human-manual",
                    display_name="人类说明书",
                    audio_dir=audio_root / "人类说明书",
                    transcript_dir=output_root / "人类说明书",
                    prefix_width=2,
                ),
            ]

            items = scan_audio_sources(series)

            self.assertEqual(
                [item.source_path.name for item in items],
                [
                    "01. 第一讲.mp3",
                    "02. 第二讲.mp3",
                    "20260328. 「人類說明書」关系底牌 [abc123].mp3",
                ],
            )
            self.assertEqual(items[0].transcript_path.name, "01. 第一讲.md")
            self.assertEqual(items[2].source_id, "human-manual/关系底牌")
            self.assertEqual(
                items[2].transcript_path.name,
                "20260328. 「人類說明書」关系底牌 [abc123].md",
            )

    def test_manifest_round_trip_and_pending_detection(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest = PipelineManifest(manifest_path)
            manifest.upsert(
                source_id="天地大道/01. 第一讲.mp3",
                values={
                    "status": "completed",
                    "series_key": "tiandi",
                    "job_id": "job-1",
                    "transcript_path": "天地大道/01_第一讲.md",
                },
            )
            manifest.upsert(
                source_id="天地大道/02. 第二讲.mp3",
                values={
                    "status": "submitted",
                    "series_key": "tiandi",
                    "job_id": "job-2",
                },
            )
            manifest.save()

            loaded = PipelineManifest(manifest_path)
            loaded.load()

            self.assertEqual(loaded.get("天地大道/01. 第一讲.mp3")["job_id"], "job-1")
            self.assertEqual(
                loaded.pending_source_ids(),
                ["天地大道/02. 第二讲.mp3"],
            )

    def test_pending_source_ids_excludes_terminal_failures(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest = PipelineManifest(manifest_path)
            manifest.upsert(
                source_id="天地大道/03. 第三讲.mp3",
                values={"status": "failed", "retry_count": 3},
            )
            manifest.upsert(
                source_id="天地大道/04. 第四讲.mp3",
                values={"status": "retry_pending", "retry_count": 1},
            )

            self.assertEqual(manifest.pending_source_ids(), ["天地大道/04. 第四讲.mp3"])

    def test_load_series_map_expands_document_root_placeholder(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            document_root = workspace / "文稿"
            series_map_path = workspace / ".pipeline" / "series_map.json"
            series_map_path.parent.mkdir(parents=True)
            series_map_path.write_text(
                json.dumps(
                    {
                        "series": [
                            {
                                "key": "tiandi",
                                "display_name": "天地大道",
                                "audio_dir": "${HOME}/Music/天地大道",
                                "transcript_dir": "${DOCUMENT_ROOT}/录音稿/天地大道",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DOCUMENT_ROOT": str(document_root), "HOME": str(workspace / "home")}, clear=False):
                loaded = load_series_map(series_map_path)

            self.assertEqual(loaded[0].transcript_dir, document_root / "录音稿" / "天地大道")
            self.assertEqual(loaded[0].audio_dir, workspace / "home" / "Music" / "天地大道")

    def test_pipeline_paths_from_workspace_uses_document_root_for_article_output(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            document_root = workspace / "文稿"

            with patch.dict(os.environ, {"DOCUMENT_ROOT": str(document_root)}, clear=False):
                paths = PipelinePaths.from_workspace(workspace)

            self.assertEqual(paths.article_dir, document_root / "拆解文章")


if __name__ == "__main__":
    unittest.main()
