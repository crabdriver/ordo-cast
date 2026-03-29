from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from audio_pipeline.article_splitter import (
    ArticleDraft,
    derive_article_source_dir_name,
    resolve_article_output_dir,
    should_generate_articles,
    write_articles,
)


class ArticleSplitterTests(unittest.TestCase):
    def test_should_generate_articles_skips_when_review_pending_and_not_allowed(self) -> None:
        self.assertFalse(
            should_generate_articles(
                {
                    "status": "completed",
                    "article_status": "pending",
                    "review_status": "pending",
                },
                allow_pending_review=False,
            )
        )

    def test_should_generate_articles_when_review_pending_if_allowed(self) -> None:
        self.assertTrue(
            should_generate_articles(
                {
                    "status": "completed",
                    "article_status": "pending",
                    "review_status": "pending",
                },
                allow_pending_review=True,
            )
        )

    def test_should_generate_articles_when_review_status_missing(self) -> None:
        self.assertTrue(
            should_generate_articles(
                {
                    "status": "completed",
                    "article_status": "pending",
                },
                allow_pending_review=False,
            )
        )

    def test_should_generate_articles_allows_base_transcript_even_if_normalization_failed(self) -> None:
        self.assertTrue(
            should_generate_articles(
                {
                    "status": "completed",
                    "normalization_status": "failed",
                    "review_status": "reviewed",
                },
                allow_pending_review=False,
            )
        )

    def test_resolve_article_output_dir_avoids_cross_series_collisions(self) -> None:
        base = Path("/tmp/articles")

        self.assertEqual(resolve_article_output_dir(base, "天地大道", "03_关系底牌"), base / "天地大道" / "03_关系底牌")
        self.assertEqual(resolve_article_output_dir(base, "人类说明书", "03_关系底牌"), base / "人类说明书" / "03_关系底牌")

    def test_derive_article_source_dir_name_uses_issue_number_and_display_title(self) -> None:
        self.assertEqual(
            derive_article_source_dir_name(
                {
                    "sequence": 3,
                    "display_title": "关系底牌",
                    "source_name": "20260328. 关系底牌 [abc123].mp3",
                }
            ),
            "03_关系底牌",
        )

    def test_write_articles_uses_numbered_filenames_and_strips_h1_heading(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            drafts = [
                ArticleDraft(
                    title="关系里最伤人的不是争吵",
                    body="# 关系里最伤人的不是争吵\n\n真正伤人的，是长期轻视。",
                ),
                ArticleDraft(
                    title="越想证明自己越容易失衡",
                    body="先稳住自己，再谈输出。",
                ),
            ]

            written = write_articles(
                output_dir=output_dir,
                issue_number="11",
                drafts=drafts,
            )

            self.assertEqual(
                [path.name for path in written],
                [
                    "11-01_关系里最伤人的不是争吵.md",
                    "11-02_越想证明自己越容易失衡.md",
                ],
            )
            first_body = written[0].read_text(encoding="utf-8")
            self.assertNotIn("# 关系里最伤人的不是争吵", first_body)
            self.assertTrue(first_body.startswith("真正伤人的"))

    def test_write_articles_refuses_to_overwrite_existing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            existing = output_dir / "11-01_关系里最伤人的不是争吵.md"
            existing.write_text("人工修改过的文章\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                write_articles(
                    output_dir=output_dir,
                    issue_number="11",
                    drafts=[
                        ArticleDraft(
                            title="关系里最伤人的不是争吵",
                            body="新的自动稿件",
                        )
                    ],
                )


if __name__ == "__main__":
    unittest.main()
