from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from experimental_llm_writer.normalize_transcript import main


class NormalizeTranscriptScriptTests(unittest.TestCase):
    def test_main_writes_task_log_for_successful_normalization(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            pipeline_dir = workspace / ".pipeline"
            pipeline_dir.mkdir(parents=True, exist_ok=True)
            # Create subproject prompts dir
            prompts_dir = workspace / "experimental_llm_writer" / "prompts"
            prompts_dir.mkdir(parents=True, exist_ok=True)
            (prompts_dir / "clean_transcript.md").write_text("prompt content", encoding="utf-8")
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

            # We need to mock build_text_client_from_env from the correct module
            with patch("sys.argv", ["normalize_transcript.py", "--workspace-root", str(workspace)]), patch(
                "experimental_llm_writer.normalize_transcript.build_text_client_from_env",
                return_value=None,
            ):
                # Ensure the test prompts are located under experimental_llm_writer/prompts Relative to this script.
                # Since the main function runs experimental_llm_writer.normalize_transcript,
                # we mock __file__ or just ensure the workspace root has experimental_llm_writer/prompts
                # Actually, __file__ in normalize_transcript will point to experimental_llm_writer/normalize_transcript.py,
                # so Path(__file__).parent / "prompts" / "clean_transcript.md" is evaluated relative to the actual installed package.
                # Wait, in the test runner, normalize_transcript.py is at:
                # /Users/wizard/work_2025/tiandiworkspace/experimental_llm_writer/normalize_transcript.py.
                # So Path(__file__).parent / "prompts" / "clean_transcript.md" evaluates to the real repo's prompts dir, which is fine!
                exit_code = main()

            self.assertEqual(exit_code, 0)
            events_path = workspace / ".pipeline" / "logs" / "events.jsonl"
            self.assertTrue(events_path.exists())
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            stages = {(event["stage"], event["status"]) for event in events}
            self.assertIn(("normalize_transcript", "success"), stages)


if __name__ == "__main__":
    unittest.main()
