from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from audio_pipeline.task_logging import PipelineTaskLogger


class PipelineTaskLoggerTests(unittest.TestCase):
    def test_logger_writes_event_summary_and_latest_status(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            logger = PipelineTaskLogger(workspace_root=workspace, module="download")

            logger.log_event(
                stage="scan",
                status="success",
                message="已完成栏目扫描",
                series_key="tiandi",
                details={"audio_files": 3},
            )
            logger.log_event(
                stage="download",
                status="success",
                message="新增 1 个音频",
                series_key="tiandi",
                title_key="diyike",
                display_title="第一课",
            )
            logger.finish(status="success", message="本轮下载结束")

            events_path = workspace / ".pipeline" / "logs" / "events.jsonl"
            latest_path = workspace / ".pipeline" / "logs" / "latest_status.json"
            summary_path = workspace / ".pipeline" / "logs" / "runs" / f"{logger.run_id}.summary.json"

            self.assertTrue(events_path.exists())
            self.assertTrue(latest_path.exists())
            self.assertTrue(summary_path.exists())

            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(events[0]["module"], "download")
            self.assertEqual(events[0]["stage"], "scan")
            self.assertEqual(events[1]["title_key"], "diyike")

            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest["run_id"], logger.run_id)
            self.assertEqual(latest["status"], "success")

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["module"], "download")
            self.assertEqual(summary["event_counts"]["scan.success"], 1)
            self.assertEqual(summary["event_counts"]["download.success"], 1)


if __name__ == "__main__":
    unittest.main()
