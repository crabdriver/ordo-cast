from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from audio_pipeline.config import PipelinePaths, SeriesDefinition
from audio_pipeline.manifest import PipelineManifest
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
            entry = manifest.get("天地大道/11. 第一课.mp3")
            self.assertEqual(entry["status"], "completed")
            self.assertTrue(Path(entry["raw_transcript_path"]).exists())
            self.assertTrue(Path(entry["transcript_path"]).exists())
            self.assertEqual(entry["review_status"], "pending")

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
            entry = manifest.get("天地大道/11. 第一课.mp3")
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
            entry = manifest.get("天地大道/11. 第一课.mp3")
            self.assertEqual(entry["status"], "failed")
            self.assertIn("Is a directory", entry["error_message"])


if __name__ == "__main__":
    unittest.main()
