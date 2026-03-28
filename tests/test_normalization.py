from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from audio_pipeline.normalization import (
    build_normalization_manifest_update,
    compute_text_checksum,
    format_transcript_markdown,
    scrub_transcript_text,
    should_skip_normalization,
)


class NormalizationTests(unittest.TestCase):
    def test_build_normalization_manifest_update_invalidates_previous_articles(self) -> None:
        update = build_normalization_manifest_update(
            previous_entry={
                "article_status": "completed",
                "article_paths": ["/tmp/article.md"],
                "review_status": "reviewed",
            },
            markdown="新的长稿",
        )

        self.assertEqual(update["review_status"], "pending")
        self.assertEqual(update["article_status"], "pending")
        self.assertEqual(update["article_paths"], [])

    def test_should_skip_normalization_when_file_was_manually_edited(self) -> None:
        existing = "人工修订后的内容"
        entry = {
            "transcript_checksum": compute_text_checksum("原始自动稿"),
            "normalization_status": "completed",
            "review_status": "pending",
        }

        self.assertTrue(should_skip_normalization(existing_text=existing, entry=entry, force=False))

    def test_should_not_skip_when_force_is_enabled(self) -> None:
        existing = "人工修订后的内容"
        entry = {
            "transcript_checksum": compute_text_checksum("原始自动稿"),
            "normalization_status": "completed",
            "review_status": "reviewed",
        }

        self.assertFalse(should_skip_normalization(existing_text=existing, entry=entry, force=True))

    def test_scrub_transcript_text_removes_timestamps_and_repeated_whitespace(self) -> None:
        raw = """
        [00:00:01] 大家好，  现在开始。

        [00:00:05]   今天继续。

        """

        cleaned = scrub_transcript_text(raw)

        self.assertEqual(cleaned, "大家好， 现在开始。\n\n今天继续。")

    def test_format_transcript_markdown_writes_metadata_header(self) -> None:
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "11_关系的底牌.md"
            markdown = format_transcript_markdown(
                series_name="天地大道",
                source_name="11. 关系的底牌.mp3",
                cleaned_text="第一段。\n\n第二段。",
                reviewed=False,
            )
            target.write_text(markdown, encoding="utf-8")

            content = target.read_text(encoding="utf-8")

            self.assertIn("系列：天地大道", content)
            self.assertIn("原音频：11. 关系的底牌.mp3", content)
            self.assertIn("状态：待复核", content)
            self.assertTrue(content.rstrip().endswith("第二段。"))


if __name__ == "__main__":
    unittest.main()
