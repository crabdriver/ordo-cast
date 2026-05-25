from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import MagicMock

from audio_pipeline.json_utils import parse_articles_payload, parse_json_from_llm, strip_llm_json_fences


class JsonUtilsTests(unittest.TestCase):
    def test_strip_llm_json_fences(self) -> None:
        raw = "```json\n{\"a\": 1}\n```"
        self.assertEqual(strip_llm_json_fences(raw).strip(), '{"a": 1}')

    def test_parse_json_from_llm_with_extra_text(self) -> None:
        raw = '说明如下：\n```JSON\n{"x": 1}\n```\n完'
        data = parse_json_from_llm(raw)
        self.assertEqual(data, {"x": 1})

    def test_parse_articles_payload(self) -> None:
        raw = '{"articles": [{"title": "A", "body": "b"}]}'
        items = parse_articles_payload(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "A")


class ManifestCopyTests(unittest.TestCase):
    def test_get_returns_copy(self) -> None:
        from audio_pipeline.manifest import PipelineManifest

        with TemporaryDirectory() as tmp:
            mp = Path(tmp) / "manifest.json"
            m = PipelineManifest(mp)
            m.entries["a"] = {"status": "pending"}
            got = m.get("a")
            got["status"] = "hacked"
            self.assertEqual(m.entries["a"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
