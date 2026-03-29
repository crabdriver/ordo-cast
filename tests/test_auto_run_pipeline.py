from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from scripts.auto_run_pipeline import main


class AutoRunPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dotenv_patcher = patch("dotenv.load_dotenv", lambda *_a, **_k: None)
        self._dotenv_patcher.start()

    def tearDown(self) -> None:
        self._dotenv_patcher.stop()

    def test_main_runs_to_success_and_passes_split_flags(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            audio_dir = workspace / "audio" / "天地大道"
            audio_dir.mkdir(parents=True)
            series = [SimpleNamespace(key="tiandi", display_name="天地大道", audio_dir=audio_dir)]
            seen_split = {"command": None}

            def fake_run(command, cwd=None, check=False):
                del cwd, check
                script = command[1]
                if script == "scripts/download_youtube.py":
                    (audio_dir / "01. 第一课.mp3").write_bytes(b"mp3")
                elif script == "scripts/transcribe_batch.py":
                    (workspace / ".pipeline").mkdir(parents=True, exist_ok=True)
                    (workspace / ".pipeline" / "manifest.json").write_text(
                        json.dumps(
                            {
                                "entries": {
                                    "tiandi/第一课": {
                                        "series_key": "tiandi",
                                        "status": "completed",
                                        "job_id": "job-1",
                                        "submitted_audio_sha1": "sha1",
                                        "normalization_status": "pending",
                                        "article_status": "pending",
                                    }
                                }
                            },
                            ensure_ascii=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    return SimpleNamespace(returncode=0)
                elif script == "scripts/normalize_transcript.py":
                    manifest_path = workspace / ".pipeline" / "manifest.json"
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    data["entries"]["tiandi/第一课"]["normalization_status"] = "completed"
                    manifest_path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
                elif script == "scripts/split_to_wechat_articles.py":
                    seen_split["command"] = command
                    manifest_path = workspace / ".pipeline" / "manifest.json"
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    data["entries"]["tiandi/第一课"]["article_status"] = "completed"
                    manifest_path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with patch("scripts.auto_run_pipeline.load_series_map", return_value=series), patch(
                "subprocess.run",
                side_effect=fake_run,
            ), patch(
                "sys.argv",
                [
                    "auto_run_pipeline.py",
                    "--workspace-root",
                    str(workspace),
                    "--max-cycles",
                    "1",
                    "--expected-articles",
                    "14",
                ],
            ):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertIn("--allow-pending-review", seen_split["command"])
        self.assertIn("--expected-articles", seen_split["command"])
        self.assertIn("14", seen_split["command"])

    def test_main_returns_incomplete_after_idle_cycles_without_progress(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            audio_dir = workspace / "audio" / "天地大道"
            audio_dir.mkdir(parents=True)
            series = [SimpleNamespace(key="tiandi", display_name="天地大道", audio_dir=audio_dir)]

            def fake_run(command, cwd=None, check=False):
                del cwd, check
                script = command[1]
                if script == "scripts/transcribe_batch.py":
                    (workspace / ".pipeline").mkdir(parents=True, exist_ok=True)
                    (workspace / ".pipeline" / "manifest.json").write_text(
                        json.dumps(
                            {
                                "entries": {
                                    "tiandi/第一课": {
                                        "series_key": "tiandi",
                                        "status": "submitted",
                                        "job_id": "job-1",
                                        "submitted_audio_sha1": "sha1",
                                        "normalization_status": "pending",
                                        "article_status": "pending",
                                    }
                                }
                            },
                            ensure_ascii=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    return SimpleNamespace(returncode=3)
                return SimpleNamespace(returncode=0)

            with patch("scripts.auto_run_pipeline.load_series_map", return_value=series), patch(
                "subprocess.run",
                side_effect=fake_run,
            ), patch(
                "sys.argv",
                [
                    "auto_run_pipeline.py",
                    "--workspace-root",
                    str(workspace),
                    "--max-cycles",
                    "2",
                    "--max-idle-cycles",
                    "1",
                    "--sleep-seconds",
                    "0",
                    "--skip-download",
                    "--skip-split",
                ],
            ):
                exit_code = main()

        self.assertEqual(exit_code, 3)


if __name__ == "__main__":
    unittest.main()
