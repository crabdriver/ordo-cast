from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.download_youtube import main


class DownloadYouTubeScriptTests(unittest.TestCase):
    def test_main_returns_nonzero_when_all_selected_sources_missing_urls(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            fake_series = [SimpleNamespace(key="tiandi", display_name="天地大道")]
            fake_sources = [SimpleNamespace(series_key="tiandi", channel_url="")]
            with patch("scripts.download_youtube.ensure_download_layout", return_value=workspace / ".pipeline" / "youtube_sources.json"), patch(
                "scripts.download_youtube.load_series_map",
                return_value=fake_series,
            ), patch(
                "scripts.download_youtube.load_youtube_sources",
                return_value=fake_sources,
            ), patch(
                "sys.argv",
                ["download_youtube.py", "--workspace-root", str(workspace), "--all"],
            ):
                exit_code = main()

        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
