import unittest

from audio_pipeline.manifest import PipelineManifest
from audio_pipeline.manifest_state import (
    KNOWN_TRANSCRIPTION_STATUSES,
    TranscriptionStatus,
    validate_transcription_status_transition,
)


class ManifestStateValidationTests(unittest.TestCase):
    def test_known_statuses_cover_enum(self) -> None:
        self.assertEqual({s.value for s in TranscriptionStatus}, KNOWN_TRANSCRIPTION_STATUSES)

    def test_first_status_write_allowed(self) -> None:
        validate_transcription_status_transition(None, "completed")
        validate_transcription_status_transition("", "submitted")

    def test_completed_to_pending_allowed(self) -> None:
        validate_transcription_status_transition("completed", "pending")

    def test_completed_to_failed_allowed(self) -> None:
        validate_transcription_status_transition("completed", "failed")

    def test_completed_to_submitted_forbidden(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_transcription_status_transition("completed", "submitted")
        self.assertIn("非法跳转", str(ctx.exception))

    def test_failed_to_completed_forbidden(self) -> None:
        with self.assertRaises(ValueError):
            validate_transcription_status_transition("failed", "completed")

    def test_manifest_upsert_enforces_transition(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            m = PipelineManifest(path)
            m.upsert("a", {"status": "completed", "series_key": "x"})
            with self.assertRaises(ValueError):
                m.upsert("a", {"status": "submitted"})


if __name__ == "__main__":
    unittest.main()
