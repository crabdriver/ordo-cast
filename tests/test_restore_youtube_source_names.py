import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from audio_pipeline.config import PipelinePaths
from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.restore_youtube_source_names import restore_workspace_youtube_source_names


class RestoreYoutubeSourceNamesTests(unittest.TestCase):
    def test_restore_renames_renumbered_entry_using_playlist_index(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            document_root = workspace / "文稿"
            pipeline_dir = workspace / ".pipeline"
            pipeline_dir.mkdir(parents=True)
            (pipeline_dir / "youtube_sources.json").write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "series_key": "tiandi",
                                "channel_url": "https://example.com/playlist",
                                "download_mode": "audio_only_mp3",
                                "archive_file": ".pipeline/youtube_archive/tiandi.txt",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (pipeline_dir / "series_map.json").write_text(
                json.dumps(
                    {
                        "series": [
                            {
                                "key": "tiandi",
                                "display_name": "天地大道",
                                "audio_dir": str(workspace / "audio" / "天地大道"),
                                "transcript_dir": "${DOCUMENT_ROOT}/录音稿/天地大道",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            old_name = "09. 【天地大道之人間道】你的“人生劇本”卡在哪了？.mp3"
            canonical = "20260112. 【天地大道之人間道】你的“人生劇本”卡在哪了？ [CBy8pcwk1jg].mp3"
            old_transcript = document_root / "录音稿" / "天地大道" / f"{Path(old_name).stem}.md"
            old_transcript.parent.mkdir(parents=True, exist_ok=True)
            old_transcript.write_text("正文\n", encoding="utf-8")

            manifest = PipelineManifest(pipeline_dir / "manifest.json")
            manifest.upsert(
                "tiandi/之人間道你的人生劇本卡在哪了",
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "title_key": "之人間道你的人生劇本卡在哪了",
                    "display_title": "之人間道你的“人生劇本”卡在哪了？",
                    "source_name": old_name,
                    "source_path": str(workspace / "audio" / "天地大道" / old_name),
                    "transcript_path": str(old_transcript),
                },
            )
            manifest.save()

            def fake_runner(command: list[str]) -> str:
                return json.dumps(
                    {
                        "entries": [
                            {
                                "upload_date": "20260112",
                                "title": "【天地大道之人間道】你的“人生劇本”卡在哪了？",
                                "id": "CBy8pcwk1jg",
                            }
                        ]
                    },
                    ensure_ascii=False,
                )

            os.environ["DOCUMENT_ROOT"] = str(document_root)
            try:
                from audio_pipeline import youtube_naming as naming_module

                original = naming_module._default_playlist_runner
                naming_module._default_playlist_runner = lambda command: fake_runner(command)
                try:
                    summary = restore_workspace_youtube_source_names(workspace, dry_run=False)
                finally:
                    naming_module._default_playlist_runner = original
            finally:
                os.environ.pop("DOCUMENT_ROOT", None)

            self.assertEqual(summary.restored_entries, 1)
            new_transcript = document_root / "录音稿" / "天地大道" / f"{Path(canonical).stem}.md"
            self.assertTrue(new_transcript.exists())
            loaded = PipelineManifest(pipeline_dir / "manifest.json")
            loaded.load()
            entry = loaded.get("tiandi/之人間道你的人生劇本卡在哪了")
            self.assertEqual(entry["source_name"], canonical)
            self.assertEqual(entry["transcript_path"], str(new_transcript))


if __name__ == "__main__":
    unittest.main()
