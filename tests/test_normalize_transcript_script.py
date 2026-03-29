from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from scripts.normalize_transcript import main


class NormalizeTranscriptScriptTests(unittest.TestCase):
    def test_main_writes_task_log_for_successful_normalization(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            pipeline_dir = workspace / ".pipeline"
            pipeline_dir.mkdir(parents=True, exist_ok=True)
            (workspace / "prompts").mkdir(parents=True, exist_ok=True)
            raw_path = pipeline_dir / "raw_transcripts" / "天地大道" / "03. 关系底牌.txt"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("[00:00:01] 正文内容", encoding="utf-8")
            transcript_path = workspace / "天地大道" / "03_关系底牌.md"
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            (pipeline_dir / "series_map.json").write_text(
                json.dumps(
                    {
                        "series": [
                            {
                                "key": "tiandi",
                                "display_name": "天地大道",
                                "audio_dir": str(workspace / "audio" / "天地大道"),
                                "transcript_dir": "天地大道",
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (pipeline_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "entries": {
                            "tiandi/关系底牌": {
                                "status": "completed",
                                "series_key": "tiandi",
                                "source_name": "03. 关系底牌.mp3",
                                "raw_transcript_path": str(raw_path),
                                "transcript_path": str(transcript_path),
                                "normalization_status": "pending",
                            }
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("sys.argv", ["normalize_transcript.py", "--workspace-root", str(workspace)]), patch(
                "scripts.normalize_transcript.build_text_client_from_env",
                return_value=None,
            ):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            events_path = workspace / ".pipeline" / "logs" / "events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            stages = {(event["stage"], event["status"]) for event in events}
            self.assertIn(("normalize_transcript", "success"), stages)


if __name__ == "__main__":
    unittest.main()
