import unittest
from unittest.mock import patch

from scripts.run_full_pipeline import main


class RunFullPipelineTests(unittest.TestCase):
    def test_main_runs_download_transcribe_normalize_and_split_by_default(self) -> None:
        calls = []

        def fake_run(command, cwd=None, check=None):
            calls.append((command, cwd, check))

        with patch("sys.argv", ["run_full_pipeline.py", "--workspace-root", "/tmp/workspace"]), patch(
            "subprocess.run",
            side_effect=fake_run,
        ):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual([call[0][1] for call in calls], [
            "scripts/download_youtube.py",
            "scripts/transcribe_batch.py",
            "scripts/normalize_transcript.py",
            "scripts/split_to_wechat_articles.py",
        ])
        self.assertIn("--all", calls[0][0])
        self.assertIn("--wait", calls[1][0])

    def test_main_propagates_series_and_skip_flags(self) -> None:
        calls = []

        def fake_run(command, cwd=None, check=None):
            calls.append((command, cwd, check))

        with patch(
            "sys.argv",
            [
                "run_full_pipeline.py",
                "--workspace-root",
                "/tmp/workspace",
                "--series",
                "tiandi",
                "--skip-download",
                "--skip-split",
            ],
        ), patch("subprocess.run", side_effect=fake_run):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual([call[0][1] for call in calls], [
            "scripts/transcribe_batch.py",
            "scripts/normalize_transcript.py",
        ])
        self.assertIn("--series", calls[0][0])
        self.assertIn("tiandi", calls[0][0])
        self.assertIn("--series", calls[1][0])
        self.assertIn("tiandi", calls[1][0])


if __name__ == "__main__":
    unittest.main()
