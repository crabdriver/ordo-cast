import unittest
from subprocess import CalledProcessError
from unittest.mock import patch

from scripts.run_full_pipeline import main


class RunFullPipelineTests(unittest.TestCase):
    def test_main_runs_download_and_transcribe_by_default(self) -> None:
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
            ],
        ), patch("subprocess.run", side_effect=fake_run):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual([call[0][1] for call in calls], [
            "scripts/transcribe_batch.py",
        ])
        self.assertIn("--series", calls[0][0])
        self.assertIn("tiandi", calls[0][0])

    def test_main_stops_after_transcribe_when_incomplete(self) -> None:
        calls = []

        def fake_run(command, cwd=None, check=None):
            del cwd, check
            calls.append(command)
            if command[1] == "scripts/transcribe_batch.py":
                raise CalledProcessError(3, command)

        with patch("sys.argv", ["run_full_pipeline.py", "--workspace-root", "/tmp/workspace"]), patch(
            "subprocess.run",
            side_effect=fake_run,
        ):
            exit_code = main()

        self.assertEqual(exit_code, 3)
        self.assertEqual([call[1] for call in calls], [
            "scripts/download_youtube.py",
            "scripts/transcribe_batch.py",
        ])


if __name__ == "__main__":
    unittest.main()
