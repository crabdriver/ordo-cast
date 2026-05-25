import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from audio_pipeline.config import SeriesDefinition
from audio_pipeline.youtube_naming import (
    build_youtube_source_name,
    build_youtube_source_name_from_video,
    is_youtube_source_name,
    load_youtube_names_from_events,
    truncate_title_to_bytes,
)


class YoutubeNamingTests(unittest.TestCase):
    def test_is_youtube_source_name(self) -> None:
        self.assertTrue(
            is_youtube_source_name(
                "20260112. 【天地大道之人間道】你的“人生劇本”卡在哪了？ [CBy8pcwk1jg].mp3"
            )
        )
        self.assertFalse(is_youtube_source_name("09. 【天地大道之人間道】你的“人生劇本”卡在哪了？.mp3"))

    def test_build_youtube_source_name_truncates_title_bytes(self) -> None:
        long_title = "标题" + ("長" * 100)
        source_name = build_youtube_source_name(
            upload_date="20260112",
            title=long_title,
            video_id="abc123",
        )
        stem = Path(source_name).stem
        self.assertLessEqual(len(stem.encode("utf-8")), 180 + len("20260112. ") + len(" [abc123]"))

    def test_build_youtube_source_name_from_video(self) -> None:
        source_name = build_youtube_source_name_from_video(
            {
                "upload_date": "20251117",
                "title": "為什麼段永平、巴菲特能穿越週期？揭秘頂級強者的“道果”與“價值回歸”【天地大道18】",
                "id": "W4e7lft40Lk",
            }
        )
        self.assertTrue(source_name.startswith("20251117. "))
        self.assertIn("【天地大道18】", source_name)
        self.assertTrue(source_name.endswith("[W4e7lft40Lk].mp3"))

    def test_load_youtube_names_from_events(self) -> None:
        with TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"
            events_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "series_key": "tiandi",
                                "title_key": "demo-key",
                                "source_path": "/tmp/20260112. Demo [abc123].mp3",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "series_key": "tiandi",
                                "title_key": "demo-key",
                                "source_path": "/tmp/09. Demo.mp3",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            mapping = load_youtube_names_from_events(events_path)
            self.assertEqual(mapping[("tiandi", "demo-key")], "20260112. Demo [abc123].mp3")

    def test_truncate_title_to_bytes(self) -> None:
        self.assertEqual(truncate_title_to_bytes("abc", 10), "abc")


if __name__ == "__main__":
    unittest.main()
