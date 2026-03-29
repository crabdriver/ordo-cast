from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import MagicMock

from audio_pipeline.json_utils import parse_articles_payload, parse_json_from_llm, strip_llm_json_fences
from audio_pipeline.llm import OpenAICompatibleTextClient


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


class PromptRenderTests(unittest.TestCase):
    def test_render_prompt_replaces_only_known_placeholders(self) -> None:
        fake = types.ModuleType("openai")
        fake.OpenAI = lambda **kwargs: MagicMock()
        prior = sys.modules.get("openai")
        sys.modules["openai"] = fake
        try:
            client = OpenAICompatibleTextClient(api_key="k", base_url="http://x", model="m")
        finally:
            if prior is None:
                sys.modules.pop("openai", None)
            else:
                sys.modules["openai"] = prior

        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.md"
            p.write_text(
                '原则：{principles_text}\n\n'
                'JSON 示例含花括号：\n'
                '{\n  "articles": [{"title": "t", "body": "b"}]\n}\n\n'
                '期号：{issue_number}\n\n'
                '正文含花括号 {curly}：{transcript_text}\n',
                encoding="utf-8",
            )
            out = client.render_prompt(
                p,
                {
                    "principles_text": "P",
                    "issue_number": "03",
                    "transcript_text": "含 {字面量} 与 {braces}",
                },
            )
            self.assertIn("原则：P", out)
            self.assertIn('"articles"', out)
            self.assertIn("期号：03", out)
            self.assertIn("含 {字面量} 与 {braces}", out)


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
