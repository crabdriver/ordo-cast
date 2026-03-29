from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta, timezone
import json
import unittest

from audio_pipeline.config import PipelinePaths, SeriesDefinition
from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.task_logging import PipelineTaskLogger
from audio_pipeline.transcription import AbstractTranscriptionProvider, TranscriptionJobState
from audio_pipeline.workflow import BatchTranscriptionWorkflow


class FakeProvider(AbstractTranscriptionProvider):
    def __init__(self) -> None:
        self.created_jobs: dict[str, str] = {}

    def submit(self, audio_path: Path) -> str:
        job_id = f"job-{audio_path.stem}"
        self.created_jobs[str(audio_path)] = job_id
        return job_id

    def poll(self, job_id: str) -> TranscriptionJobState:
        return TranscriptionJobState(
            status="completed",
            text=f"转录结果 {job_id}",
            error_message=None,
        )


class WorkflowTests(unittest.TestCase):
    def test_completed_legacy_filename_key_is_migrated_to_stable_title_key(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "人类说明书"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "03. 「人類說明書」关系底牌.mp3"
            audio_path.write_bytes(b"fake mp3")
            transcript_dir = root / "workspace" / "人类说明书"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"
            series = [
                SeriesDefinition(
                    key="human-manual",
                    display_name="人类说明书",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            manifest.upsert(
                "人类说明书/03. 「人類說明書」关系底牌.mp3",
                {
                    "status": "completed",
                    "series_key": "human-manual",
                    "source_path": str(audio_path),
                    "source_name": audio_path.name,
                    "transcript_path": str(transcript_dir / "03_人類說明書关系底牌.md"),
                },
            )
            manifest.save()
            provider = FakeProvider()
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=provider,
            )

            workflow.run_once()

            manifest.load()
            self.assertEqual(provider.created_jobs, {})
            self.assertEqual(manifest.get("human-manual/关系底牌")["status"], "completed")
            self.assertEqual(manifest.get("人类说明书/03. 「人類說明書」关系底牌.mp3"), {})

    def test_completed_entry_resubmits_when_same_title_audio_content_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"new content")
            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"
            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            manifest.upsert(
                "tiandi/第一课",
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_path": str(audio_path),
                    "source_name": audio_path.name,
                    "audio_sha1": "old-sha1",
                    "submitted_audio_sha1": "old-sha1",
                    "transcript_path": str(transcript_dir / "11_第一课.md"),
                },
            )
            manifest.save()
            provider = FakeProvider()
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=provider,
            )

            workflow.run_once()

            manifest.load()
            entry = manifest.get("tiandi/第一课")
            self.assertEqual(entry["status"], "completed")
            self.assertNotEqual(entry["submitted_audio_sha1"], "old-sha1")
            self.assertEqual(provider.created_jobs[str(audio_path)], "job-11. 第一课")

    def test_run_once_writes_internal_task_log_for_completed_transcript(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"fake mp3")
            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"
            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            logger = PipelineTaskLogger(workspace_root=paths.workspace_root, module="transcribe")
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=FakeProvider(),
                task_logger=logger,
            )

            workflow.run_once()
            logger.finish(status="success")

            events = [
                json.loads(line)
                for line in (paths.workspace_root / ".pipeline" / "logs" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            stages = {(event["stage"], event["status"]) for event in events}
            self.assertIn(("scan_sources", "success"), stages)
            self.assertIn(("transcript_completed", "success"), stages)

    def test_transient_submit_error_is_requeued_without_consuming_retry_budget(self) -> None:
        class ResetProvider(FakeProvider):
            def submit(self, audio_path: Path) -> str:
                raise RuntimeError("OSS 调用失败：RequestError: ('Connection aborted.', ConnectionResetError(54, 'Connection reset by peer'))")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"fake mp3")
            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"
            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            manifest.upsert(
                "天地大道/11. 第一课.mp3",
                {
                    "status": "failed",
                    "series_key": "tiandi",
                    "source_path": str(audio_path),
                    "source_name": audio_path.name,
                    "retry_count": 3,
                    "error_message": "OSS 调用失败：RequestError: ('Connection aborted.', ConnectionResetError(54, 'Connection reset by peer'))",
                    "raw_transcript_path": str(raw_dir / "foo.txt"),
                    "transcript_path": str(transcript_dir / "11_第一课.md"),
                },
            )
            manifest.save()
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=ResetProvider(),
                rate_limit_backoff_seconds=120,
            )

            workflow.run_once()

            manifest.load()
            entry = manifest.get("tiandi/第一课")
            self.assertEqual(entry["status"], "retry_pending")
            self.assertEqual(entry["retry_count"], 3)
            self.assertIn("Connection reset by peer", entry["error_message"])
            self.assertIn("next_retry_at", entry)

    def test_rate_limited_submit_does_not_consume_terminal_retry_budget(self) -> None:
        class SubmitRateLimitedProvider(FakeProvider):
            def submit(self, audio_path: Path) -> str:
                raise RuntimeError("HTTP Error 429: Too Many Requests")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"fake mp3")
            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"
            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            manifest.upsert(
                "天地大道/11. 第一课.mp3",
                {
                    "status": "failed",
                    "series_key": "tiandi",
                    "source_path": str(audio_path),
                    "source_name": audio_path.name,
                    "retry_count": 3,
                    "error_message": "火山 ASR 调用失败：HTTP Error 429: Too Many Requests",
                    "raw_transcript_path": str(raw_dir / "foo.txt"),
                    "transcript_path": str(transcript_dir / "11_第一课.md"),
                },
            )
            manifest.save()
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=SubmitRateLimitedProvider(),
                rate_limit_backoff_seconds=120,
            )

            workflow.run_once()

            manifest.load()
            entry = manifest.get("tiandi/第一课")
            self.assertEqual(entry["status"], "retry_pending")
            self.assertEqual(entry["retry_count"], 3)
            self.assertIn("next_retry_at", entry)

    def test_rate_limited_poll_sets_backoff_and_keeps_job(self) -> None:
        class RateLimitedProvider(FakeProvider):
            def poll(self, job_id: str) -> TranscriptionJobState:
                raise RuntimeError("HTTP Error 429: Too Many Requests")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"fake mp3")
            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"
            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            manifest.upsert(
                "天地大道/11. 第一课.mp3",
                {
                    "status": "submitted",
                    "series_key": "tiandi",
                    "source_path": str(audio_path),
                    "source_name": audio_path.name,
                    "job_id": "job-11. 第一课",
                    "raw_transcript_path": str(raw_dir / "foo.txt"),
                    "transcript_path": str(transcript_dir / "11_第一课.md"),
                },
            )
            manifest.save()
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=RateLimitedProvider(),
                rate_limit_backoff_seconds=120,
            )

            workflow.run_once()

            manifest.load()
            entry = manifest.get("tiandi/第一课")
            self.assertEqual(entry["status"], "submitted")
            self.assertEqual(entry["job_id"], "job-11. 第一课")
            self.assertIn("429", entry["error_message"])
            self.assertIn("next_retry_at", entry)

    def test_future_retry_at_skips_polling_this_round(self) -> None:
        class CountingProvider(FakeProvider):
            def __init__(self) -> None:
                super().__init__()
                self.poll_calls = 0

            def poll(self, job_id: str) -> TranscriptionJobState:
                self.poll_calls += 1
                return super().poll(job_id)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"fake mp3")
            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"
            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            manifest.upsert(
                "天地大道/11. 第一课.mp3",
                {
                    "status": "submitted",
                    "series_key": "tiandi",
                    "source_path": str(audio_path),
                    "source_name": audio_path.name,
                    "job_id": "job-11. 第一课",
                    "raw_transcript_path": str(raw_dir / "foo.txt"),
                    "transcript_path": str(transcript_dir / "11_第一课.md"),
                    "next_retry_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                },
            )
            manifest.save()
            provider = CountingProvider()
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=provider,
            )

            workflow.run_once()

            self.assertEqual(provider.poll_calls, 0)

    def test_max_polls_per_run_limits_single_round_request_volume(self) -> None:
        class CountingProvider(FakeProvider):
            def __init__(self) -> None:
                super().__init__()
                self.poll_calls = 0

            def poll(self, job_id: str) -> TranscriptionJobState:
                self.poll_calls += 1
                return TranscriptionJobState(status="processing", text=None, error_message=None)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"
            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            for idx in range(3):
                audio_path = music_dir / f"{idx+1:02d}. 第一课.mp3"
                audio_path.write_bytes(b"fake mp3")
                manifest.upsert(
                    f"天地大道/{audio_path.name}",
                    {
                        "status": "submitted",
                        "series_key": "tiandi",
                        "source_path": str(audio_path),
                        "source_name": audio_path.name,
                        "job_id": f"job-{idx}",
                        "raw_transcript_path": str(raw_dir / f"{idx}.txt"),
                        "transcript_path": str(transcript_dir / f"{idx}.md"),
                    },
                )
            manifest.save()
            provider = CountingProvider()
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=provider,
                max_polls_per_run=1,
            )

            workflow.run_once()

            self.assertEqual(provider.poll_calls, 1)

    def test_run_once_submits_jobs_and_writes_raw_transcript_cache(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"fake mp3")

            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"

            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=FakeProvider(),
            )

            workflow.run_once()

            manifest.load()
            entry = manifest.get("tiandi/第一课")
            self.assertEqual(entry["status"], "completed")
            self.assertTrue(Path(entry["raw_transcript_path"]).exists())
            self.assertTrue(Path(entry["transcript_path"]).exists())
            self.assertEqual(entry["review_status"], "pending")
            self.assertFalse(audio_path.exists())

    def test_completed_manifest_entry_deletes_existing_source_audio_when_transcript_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"fake mp3")

            transcript_dir = root / "workspace" / "天地大道"
            transcript_dir.mkdir(parents=True)
            transcript_path = transcript_dir / "11_第一课.md"
            transcript_path.write_text("# 已完成\n", encoding="utf-8")
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"

            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            manifest.upsert(
                "天地大道/11. 第一课.mp3",
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_path": str(audio_path),
                    "source_name": audio_path.name,
                    "raw_transcript_path": str(raw_dir / "11. 第一课.txt"),
                    "transcript_path": str(transcript_path),
                },
            )
            manifest.save()
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=FakeProvider(),
            )

            workflow.run_once()

            self.assertFalse(audio_path.exists())

    def test_poll_failure_keeps_job_id_for_resume_instead_of_crashing(self) -> None:
        class FlakyProvider(FakeProvider):
            def __init__(self) -> None:
                super().__init__()
                self.poll_calls = 0

            def poll(self, job_id: str) -> TranscriptionJobState:
                self.poll_calls += 1
                raise RuntimeError("temporary poll failure")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"fake mp3")

            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"

            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=FlakyProvider(),
            )

            workflow.run_once()

            manifest.load()
            entry = manifest.get("tiandi/第一课")
            self.assertEqual(entry["status"], "submitted")
            self.assertEqual(entry["job_id"], "job-11. 第一课")
            self.assertIn("temporary poll failure", entry["error_message"])

    def test_write_failure_marks_source_failed_without_stopping_batch(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            music_dir = root / "music" / "天地大道"
            music_dir.mkdir(parents=True)
            audio_path = music_dir / "11. 第一课.mp3"
            audio_path.write_bytes(b"fake mp3")

            transcript_dir = root / "workspace" / "天地大道"
            raw_dir = root / "workspace" / ".pipeline" / "raw_transcripts"
            article_dir = root / "workspace" / "拆解后文章"

            series = [
                SeriesDefinition(
                    key="tiandi",
                    display_name="天地大道",
                    audio_dir=music_dir,
                    transcript_dir=transcript_dir,
                    prefix_width=2,
                )
            ]
            paths = PipelinePaths(
                workspace_root=root / "workspace",
                manifest_path=root / "workspace" / ".pipeline" / "manifest.json",
                raw_transcript_dir=raw_dir,
                article_dir=article_dir,
                prompts_dir=root / "workspace" / "prompts",
                series_map_path=root / "workspace" / ".pipeline" / "series_map.json",
            )
            manifest = PipelineManifest(paths.manifest_path)
            workflow = BatchTranscriptionWorkflow(
                series=series,
                paths=paths,
                manifest=manifest,
                provider=FakeProvider(),
            )
            broken_target = transcript_dir / "11_第一课.md"
            broken_target.mkdir(parents=True)

            workflow.run_once()

            manifest.load()
            entry = manifest.get("tiandi/第一课")
            self.assertEqual(entry["status"], "failed")
            self.assertIn("Is a directory", entry["error_message"])


if __name__ == "__main__":
    unittest.main()
