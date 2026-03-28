from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest

from audio_pipeline.config import SeriesDefinition
from audio_pipeline.youtube_downloader import (
    YouTubeBatchDownloader,
    load_youtube_sources,
    write_default_youtube_sources,
)


class YouTubeDownloaderTests(unittest.TestCase):
    def test_write_default_youtube_sources_creates_series_key_mapping(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            config_path = workspace / ".pipeline" / "youtube_sources.json"
            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=Path("/Users/wizard/Music/天地大道"),
                    transcript_dir=workspace / "天地大道",
                ),
                SeriesDefinition(
                    key="human-manual",
                    display_name="人类说明书",
                    audio_dir=Path("/Users/wizard/Music/人类说明书"),
                    transcript_dir=workspace / "人类说明书",
                ),
            ]

            write_default_youtube_sources(config_path, series)

            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload,
                {
                    "sources": [
                        {
                            "series_key": "tiandi",
                            "channel_url": "https://www.youtube.com/playlist?list=PLwUkfFsdDFqkqU28gZ3he1VWIR5wgAC1E",
                            "download_mode": "audio_only_mp3",
                            "archive_file": ".pipeline/youtube_archive/tiandi.txt",
                        },
                        {
                            "series_key": "human-manual",
                            "channel_url": "https://www.youtube.com/playlist?list=PLwUkfFsdDFqmbqFpcO1NR8cdqp0HhFpuO",
                            "download_mode": "audio_only_mp3",
                            "archive_file": ".pipeline/youtube_archive/human-manual.txt",
                        },
                    ]
                },
            )

    def test_load_youtube_sources_resolves_relative_archive_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            config_path = workspace / ".pipeline" / "youtube_sources.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "series_key": "tiandi",
                                "channel_url": "https://www.youtube.com/@demo",
                                "download_mode": "audio_only_mp3",
                                "archive_file": ".pipeline/youtube_archive/tiandi.txt",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            sources = load_youtube_sources(config_path)

            self.assertEqual(sources[0].series_key, "tiandi")
            self.assertEqual(sources[0].archive_file, workspace / ".pipeline" / "youtube_archive" / "tiandi.txt")

    def test_sync_source_builds_audio_only_command_and_archive_path(self) -> None:
        calls: list[tuple[list[str], Path]] = []

        def fake_runner(command: list[str], cwd: Path) -> None:
            calls.append((command, cwd))

        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            audio_dir = workspace / "downloads" / "天地大道"
            series = SeriesDefinition(
                key="tiandi",
                display_name="天地大道",
                audio_dir=audio_dir,
                transcript_dir=workspace / "天地大道",
            )
            source_path = workspace / ".pipeline" / "youtube_sources.json"
            source_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "series_key": "tiandi",
                                "channel_url": "https://www.youtube.com/@tiandi",
                                "download_mode": "audio_only_mp3",
                                "archive_file": ".pipeline/youtube_archive/tiandi.txt",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = load_youtube_sources(source_path)[0]
            downloader = YouTubeBatchDownloader(
                workspace_root=workspace,
                command_runner=fake_runner,
                ffmpeg_location=Path("/tmp/fake-ffmpeg"),
            )

            downloader.sync_source(source, series)

            command, cwd = calls[0]
            self.assertEqual(cwd, workspace)
            self.assertEqual(command[:3], [sys.executable, "-m", "yt_dlp"])
            self.assertIn("--extractor-args", command)
            self.assertIn("youtube:player_client=android", command)
            self.assertIn("--extract-audio", command)
            self.assertIn("--audio-format", command)
            self.assertIn("--download-archive", command)
            self.assertIn(str(workspace / ".pipeline" / "youtube_archive" / "tiandi.txt"), command)
            self.assertIn("--ffmpeg-location", command)
            self.assertIn("/tmp/fake-ffmpeg", command)
            self.assertIn("--output", command)
            self.assertIn("%(upload_date>%Y%m%d)s. %(title).180B [%(id)s].%(ext)s", command)
            self.assertEqual(command[-1], "https://www.youtube.com/@tiandi")
            self.assertTrue(audio_dir.exists())

    def test_sync_source_skips_when_channel_url_missing(self) -> None:
        calls: list[tuple[list[str], Path]] = []

        def fake_runner(command: list[str], cwd: Path) -> None:
            calls.append((command, cwd))

        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            series = SeriesDefinition(
                key="tiandi",
                display_name="天地大道",
                audio_dir=workspace / "downloads" / "天地大道",
                transcript_dir=workspace / "天地大道",
            )
            source_path = workspace / ".pipeline" / "youtube_sources.json"
            source_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "series_key": "tiandi",
                                "channel_url": "",
                                "download_mode": "audio_only_mp3",
                                "archive_file": ".pipeline/youtube_archive/tiandi.txt",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = load_youtube_sources(source_path)[0]
            downloader = YouTubeBatchDownloader(workspace_root=workspace, command_runner=fake_runner)

            downloader.sync_source(source, series)

            self.assertEqual(calls, [])

    def test_sync_source_renames_new_downloads_to_next_numeric_sequence(self) -> None:
        calls: list[tuple[list[str], Path]] = []

        def fake_runner(command: list[str], cwd: Path) -> None:
            calls.append((command, cwd))
            (audio_dir / "20260101. 新课 A [aaa111].mp3").write_bytes(b"a")
            (audio_dir / "20260102. 新课 B [bbb222].mp3").write_bytes(b"b")

        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            audio_dir = workspace / "downloads" / "天地大道"
            audio_dir.mkdir(parents=True)
            (audio_dir / "01. 旧课.mp3").write_bytes(b"old-1")
            (audio_dir / "02. 第二课.mp3").write_bytes(b"old-2")
            series = SeriesDefinition(
                key="tiandi",
                display_name="天地大道",
                audio_dir=audio_dir,
                transcript_dir=workspace / "天地大道",
                prefix_width=2,
            )
            source_path = workspace / ".pipeline" / "youtube_sources.json"
            source_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "series_key": "tiandi",
                                "channel_url": "https://www.youtube.com/playlist?list=demo",
                                "download_mode": "audio_only_mp3",
                                "archive_file": ".pipeline/youtube_archive/tiandi.txt",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = load_youtube_sources(source_path)[0]
            downloader = YouTubeBatchDownloader(workspace_root=workspace, command_runner=fake_runner)

            downloader.sync_source(source, series)

            self.assertTrue((audio_dir / "03. 新课 A.mp3").exists())
            self.assertTrue((audio_dir / "04. 新课 B.mp3").exists())
            self.assertFalse((audio_dir / "20260101. 新课 A [aaa111].mp3").exists())
            self.assertFalse((audio_dir / "20260102. 新课 B [bbb222].mp3").exists())
            self.assertEqual(len(calls), 1)

    def test_sync_many_marks_series_unchanged_when_no_new_audio_downloaded(self) -> None:
        def fake_runner(command: list[str], cwd: Path) -> None:
            del command, cwd

        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            audio_dir = workspace / "downloads" / "天地大道"
            series = SeriesDefinition(
                key="tiandi",
                display_name="天地大道",
                audio_dir=audio_dir,
                transcript_dir=workspace / "天地大道",
            )
            source_path = workspace / ".pipeline" / "youtube_sources.json"
            source_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "series_key": "tiandi",
                                "channel_url": "https://www.youtube.com/playlist?list=demo",
                                "download_mode": "audio_only_mp3",
                                "archive_file": ".pipeline/youtube_archive/tiandi.txt",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = load_youtube_sources(source_path)[0]
            downloader = YouTubeBatchDownloader(workspace_root=workspace, command_runner=fake_runner)

            results = downloader.sync_many([source], {"tiandi": series})

            self.assertEqual(results, {"tiandi": "unchanged"})

    def test_sync_source_discards_download_when_same_title_already_exists(self) -> None:
        def fake_runner(command: list[str], cwd: Path) -> None:
            del command, cwd
            (audio_dir / "20260101. 新课 A [aaa111].mp3").write_bytes(b"a")

        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            audio_dir = workspace / "downloads" / "天地大道"
            audio_dir.mkdir(parents=True)
            (audio_dir / "01. 新课 A.mp3").write_bytes(b"old")
            series = SeriesDefinition(
                key="tiandi",
                display_name="天地大道",
                audio_dir=audio_dir,
                transcript_dir=workspace / "天地大道",
                prefix_width=2,
            )
            source_path = workspace / ".pipeline" / "youtube_sources.json"
            source_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "series_key": "tiandi",
                                "channel_url": "https://www.youtube.com/playlist?list=demo",
                                "download_mode": "audio_only_mp3",
                                "archive_file": ".pipeline/youtube_archive/tiandi.txt",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = load_youtube_sources(source_path)[0]
            downloader = YouTubeBatchDownloader(workspace_root=workspace, command_runner=fake_runner)

            status = downloader.sync_source(source, series)

            self.assertEqual(status, "unchanged")
            self.assertTrue((audio_dir / "01. 新课 A.mp3").exists())
            self.assertFalse((audio_dir / "20260101. 新课 A [aaa111].mp3").exists())


if __name__ == "__main__":
    unittest.main()
