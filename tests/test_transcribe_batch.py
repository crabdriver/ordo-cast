import os
import unittest
from unittest.mock import patch

from audio_pipeline.transcription import VolcengineBigModelProvider
from scripts.transcribe_batch import build_provider, filter_series, main, resolve_poll_interval, resolve_signed_url_expires


class BuildProviderTests(unittest.TestCase):
    def test_resolve_signed_url_expires_defaults_to_longer_value_for_idle_mode(self) -> None:
        self.assertEqual(resolve_signed_url_expires(None, "idle"), 172800)
        self.assertEqual(resolve_signed_url_expires(None, "standard"), 3600)

    def test_resolve_poll_interval_defaults_to_longer_value_for_idle_mode(self) -> None:
        self.assertEqual(resolve_poll_interval(None, "idle"), 300)
        self.assertEqual(resolve_poll_interval(None, "standard"), 30)

    def test_filter_series_supports_single_key(self) -> None:
        class Series:
            def __init__(self, key):
                self.key = key
                self.display_name = key

        filtered = filter_series([Series("tiandi"), Series("human-manual")], "tiandi")

        self.assertEqual([item.key for item in filtered], ["tiandi"])

    @patch.dict(
        os.environ,
        {
            "VOLCENGINE_APP_KEY": "fake-app-key-for-tests",
            "VOLCENGINE_ACCESS_TOKEN": "token",
            "VOLCENGINE_RESOURCE_ID": "volc.bigasr.auc_idle",
            "OSS_ACCESS_KEY_ID": "oss-ak",
            "OSS_ACCESS_KEY_SECRET": "oss-sk",
            "OSS_BUCKET": "dianliangxingkong",
            "OSS_ENDPOINT": "oss-cn-shanghai.aliyuncs.com",
            "VOLCENGINE_API_MODE": "idle",
        },
        clear=False,
    )
    def test_build_provider_returns_idle_volc_provider_when_env_ready(self) -> None:
        provider = build_provider()

        self.assertIsInstance(provider, VolcengineBigModelProvider)
        self.assertEqual(provider.resource_id, "volc.bigasr.auc_idle")
        self.assertIn("/idle/submit", provider.submit_url)

    @patch("scripts.transcribe_batch.build_provider", side_effect=RuntimeError("火山 ASR 鉴权失败，请更新 VOLCENGINE_ACCESS_TOKEN"))
    def test_main_returns_nonzero_and_prints_clear_error(self, _mock_build_provider) -> None:
        with patch("sys.argv", ["transcribe_batch.py"]), patch("builtins.print") as mock_print:
            exit_code = main()

        self.assertEqual(exit_code, 2)
        printed = " ".join(" ".join(str(arg) for arg in call.args) for call in mock_print.call_args_list)
        self.assertIn("VOLCENGINE_ACCESS_TOKEN", printed)


if __name__ == "__main__":
    unittest.main()
