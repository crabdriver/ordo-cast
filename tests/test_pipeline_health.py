import unittest

from audio_pipeline.pipeline_health import format_transcription_health_message, summarize_transcription_entries


class PipelineHealthTests(unittest.TestCase):
    def test_summarize_incomplete_when_pending_exists(self) -> None:
        report = summarize_transcription_entries(
            {
                "a": {"series_key": "tiandi", "status": "completed"},
                "b": {"series_key": "tiandi", "status": "retry_pending"},
            },
            series_keys=["tiandi"],
        )

        self.assertEqual(report.state, "incomplete")
        self.assertEqual(report.active_entries, 1)
        self.assertEqual(report.completed_entries, 1)

    def test_summarize_failed_wins_over_incomplete(self) -> None:
        report = summarize_transcription_entries(
            {
                "a": {"series_key": "tiandi", "status": "failed"},
                "b": {"series_key": "tiandi", "status": "submitted"},
            },
            series_keys=["tiandi"],
        )

        self.assertEqual(report.state, "failed")
        self.assertEqual(report.failed_entries, 1)

    def test_summarize_all_done_with_completed_only(self) -> None:
        report = summarize_transcription_entries(
            {
                "a": {"series_key": "tiandi", "status": "completed"},
            },
            series_keys=["tiandi"],
        )

        self.assertEqual(report.state, "all_done")
        self.assertEqual(report.active_entries, 0)

    def test_format_message_contains_key_counts(self) -> None:
        report = summarize_transcription_entries(
            {"a": {"series_key": "tiandi", "status": "completed"}},
            series_keys=["tiandi"],
        )
        text = format_transcription_health_message(report)
        self.assertIn("状态=all_done", text)
        self.assertIn("已完成=1", text)


if __name__ == "__main__":
    unittest.main()
