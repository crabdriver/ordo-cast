from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.migrate_youtube_filenames import migrate_workspace_to_youtube_filenames


class MigrateYoutubeFilenamesTests(unittest.TestCase):
    def test_migrate_renames_transcript_article_dir_and_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            document_root = workspace / "文稿"
            pipeline_dir = workspace / ".pipeline"
            pipeline_dir.mkdir(parents=True)
            series_map = {
                "series": [
                    {
                        "key": "tiandi",
                        "display_name": "天地大道",
                        "audio_dir": str(workspace / "audio" / "天地大道"),
                        "transcript_dir": "${DOCUMENT_ROOT}/录音稿/天地大道",
                        "prefix_width": 2,
                    }
                ]
            }
            (pipeline_dir / "series_map.json").write_text(json.dumps(series_map, ensure_ascii=False), encoding="utf-8")

            source_name = "20260204. 【天地大道之人間道】天道考場：破解人生“卡關”的終極底層算法。 [mC-CGVauZ2o].mp3"
            old_transcript = document_root / "录音稿" / "天地大道" / "20260204_之人間道天道考場：破解人生“卡關”的終極底層算法。.md"
            old_transcript.parent.mkdir(parents=True, exist_ok=True)
            old_transcript.write_text("转录正文\n", encoding="utf-8")

            old_article_dir = document_root / "拆解文章" / "天地大道" / "06_之人間道天道考場：破解人生“卡關”的終極底層算法。"
            old_article_dir.mkdir(parents=True, exist_ok=True)
            old_article = old_article_dir / "06-01_先稳住心，再谈改变：真正有用的认知训练.md"
            old_article.write_text("文章正文\n", encoding="utf-8")

            raw_dir = pipeline_dir / "raw_transcripts" / "天地大道"
            raw_dir.mkdir(parents=True, exist_ok=True)
            old_raw = raw_dir / "06. 【天地大道之人間道】天道考場：破解人生“卡關”的終極底層算法。.txt"
            old_raw.write_text("原始转录\n", encoding="utf-8")

            manifest = PipelineManifest(pipeline_dir / "manifest.json")
            manifest.upsert(
                "tiandi/天道考場",
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_name": source_name,
                    "sequence": 6,
                    "display_title": "之人間道天道考場：破解人生“卡關”的終極底層算法。",
                    "title_key": "之人間道天道考場破解人生卡關的終極底層算法",
                    "transcript_path": str(old_transcript),
                    "raw_transcript_path": str(old_raw),
                    "article_paths": [str(old_article)],
                },
            )
            manifest.save()

            import os

            old_document_root = os.environ.get("DOCUMENT_ROOT")
            os.environ["DOCUMENT_ROOT"] = str(document_root)
            try:
                summary = migrate_workspace_to_youtube_filenames(workspace, dry_run=False)
            finally:
                if old_document_root is None:
                    os.environ.pop("DOCUMENT_ROOT", None)
                else:
                    os.environ["DOCUMENT_ROOT"] = old_document_root

            expected_stem = Path(source_name).stem
            new_transcript = document_root / "录音稿" / "天地大道" / f"{expected_stem}.md"
            new_article_dir = document_root / "拆解文章" / "天地大道" / expected_stem
            new_article = new_article_dir / "20260204-01_先稳住心，再谈改变：真正有用的认知训练.md"
            new_raw = raw_dir / f"{expected_stem}.txt"

            self.assertEqual(summary.renamed_transcripts, 1)
            self.assertEqual(summary.renamed_article_dirs, 1)
            self.assertEqual(summary.renamed_article_files, 1)
            self.assertTrue(new_transcript.exists())
            self.assertTrue(new_article.exists())
            self.assertTrue(new_raw.exists())
            self.assertFalse(old_transcript.exists())
            self.assertFalse(old_article_dir.exists())

            loaded = PipelineManifest(pipeline_dir / "manifest.json")
            loaded.load()
            entry = loaded.get("tiandi/天道考場")
            self.assertEqual(Path(entry["transcript_path"]).resolve(), new_transcript.resolve())
            self.assertEqual(Path(entry["raw_transcript_path"]).resolve(), new_raw.resolve())
            self.assertEqual([Path(path).resolve() for path in entry["article_paths"]], [new_article.resolve()])

    def test_migrate_updates_transcript_source_name_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            document_root = workspace / "文稿"
            pipeline_dir = workspace / ".pipeline"
            pipeline_dir.mkdir(parents=True)
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

            source_name = "20250721. 修行多年為何命運未改？揭秘真相：先搞錢，再修道！【天地大道01】 [7Y4DyKSAfBs].mp3"
            transcript = document_root / "录音稿" / "天地大道" / f"{Path(source_name).stem}.md"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(
                "系列：天地大道\n"
                "原音频：33. 修行多年為何命運未改？揭秘真相：先搞錢，再修道！【天地大道01】.mp3\n"
                "状态：待复核\n\n---\n\n正文\n",
                encoding="utf-8",
            )

            manifest = PipelineManifest(pipeline_dir / "manifest.json")
            manifest.upsert(
                "tiandi/demo",
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_name": source_name,
                    "transcript_path": str(transcript),
                },
            )
            manifest.save()

            import os

            old_document_root = os.environ.get("DOCUMENT_ROOT")
            os.environ["DOCUMENT_ROOT"] = str(document_root)
            try:
                summary = migrate_workspace_to_youtube_filenames(workspace, dry_run=False)
            finally:
                if old_document_root is None:
                    os.environ.pop("DOCUMENT_ROOT", None)
                else:
                    os.environ["DOCUMENT_ROOT"] = old_document_root

            self.assertEqual(summary.updated_transcript_metadata, 1)
            content = transcript.read_text(encoding="utf-8")
            self.assertIn(f"原音频：{source_name}", content)
            self.assertNotIn("原音频：33.", content)


if __name__ == "__main__":
    unittest.main()
