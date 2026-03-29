from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest
from unittest.mock import patch

from audio_pipeline.manifest import PipelineManifest
from scripts.migrate_open_source_layout import migrate_workspace_layout


class MigrateOpenSourceLayoutTests(unittest.TestCase):
    def test_migrate_workspace_layout_moves_transcripts_articles_and_principles(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            document_root = workspace / "文稿"
            pipeline_dir = workspace / ".pipeline"
            pipeline_dir.mkdir(parents=True, exist_ok=True)
            old_transcript = workspace / "天地大道" / "03_关系底牌.md"
            old_transcript.parent.mkdir(parents=True, exist_ok=True)
            old_transcript.write_text("旧转录稿\n", encoding="utf-8")
            old_article = workspace / "拆解后文章" / "03-01_关系底牌.md"
            old_article.parent.mkdir(parents=True, exist_ok=True)
            old_article.write_text("旧拆稿\n", encoding="utf-8")
            (workspace / "00_文章拆解核心原则与心法.md").write_text("旧原则\n", encoding="utf-8")
            (pipeline_dir / "series_map.json").write_text(
                json.dumps(
                    {
                        "series": [
                            {
                                "key": "tiandi",
                                "display_name": "天地大道",
                                "audio_dir": str(workspace / "audio" / "天地大道"),
                                "transcript_dir": "天地大道",
                                "prefix_width": 2,
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = PipelineManifest(pipeline_dir / "manifest.json")
            manifest.upsert(
                "tiandi/关系底牌",
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "sequence": 3,
                    "display_title": "关系底牌",
                    "source_name": "20260328. 关系底牌 [abc123].mp3",
                    "transcript_path": str(old_transcript),
                    "article_status": "completed",
                    "article_paths": [str(old_article)],
                },
            )
            manifest.save()

            with patch.dict(os.environ, {"DOCUMENT_ROOT": str(document_root)}, clear=False):
                result = migrate_workspace_layout(workspace)

            new_transcript = document_root / "录音稿" / "天地大道" / "03_关系底牌.md"
            new_article = document_root / "拆解文章" / "天地大道" / "03_关系底牌" / "03-01_关系底牌.md"
            new_principles = document_root / "本地配置" / "文章拆解核心原则与心法.md"

            self.assertEqual(result["moved_transcripts"], 1)
            self.assertEqual(result["moved_articles"], 1)
            self.assertTrue(new_transcript.exists())
            self.assertTrue(new_article.exists())
            self.assertTrue(new_principles.exists())
            self.assertFalse(old_transcript.exists())
            self.assertFalse(old_article.exists())

            updated_manifest = PipelineManifest(pipeline_dir / "manifest.json")
            updated_manifest.load()
            entry = updated_manifest.get("tiandi/关系底牌")
            self.assertEqual(entry["transcript_path"], str(new_transcript))
            self.assertEqual(entry["article_paths"], [str(new_article)])

            payload = json.loads((pipeline_dir / "series_map.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["series"][0]["transcript_dir"], "${DOCUMENT_ROOT}/录音稿/天地大道")


if __name__ == "__main__":
    unittest.main()
