from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest
from unittest.mock import patch

from audio_pipeline.article_splitter import ArticleDraft
from audio_pipeline.manifest import PipelineManifest
from scripts.split_to_wechat_articles import main


class SplitToWechatArticlesScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        # 避免本机 .env 中 EXPECTED_ARTICLES_PER_TRANSCRIPT 等影响退出码断言
        self._dotenv_patcher = patch("dotenv.load_dotenv", lambda *_a, **_k: None)
        self._dotenv_patcher.start()

    def tearDown(self) -> None:
        self._dotenv_patcher.stop()

    def _prepare_workspace(self, tmp: str, entry: dict) -> Path:
        workspace = Path(tmp)
        document_root = workspace / "文稿"
        pipeline_dir = workspace / ".pipeline"
        pipeline_dir.mkdir(parents=True, exist_ok=True)
        (workspace / "prompts").mkdir(parents=True, exist_ok=True)
        (workspace / "prompts" / "split_wechat_articles.md").write_text("Issue={issue_number}\n{principles_text}\n{transcript_text}\n", encoding="utf-8")
        principles_path = document_root / "本地配置" / "文章拆解核心原则与心法.md"
        principles_path.parent.mkdir(parents=True, exist_ok=True)
        principles_path.write_text("# 文章拆解核心原则\n保持冷静\n", encoding="utf-8")
        (pipeline_dir / "series_map.json").write_text(
            json.dumps(
                {
                    "series": [
                        {
                            "key": "tiandi",
                            "display_name": "天地大道",
                            "audio_dir": str(workspace / "audio" / "天地大道"),
                            "transcript_dir": "${DOCUMENT_ROOT}/录音稿/天地大道",
                            "prefix_width": 2,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        transcript_path = Path(entry["transcript_path"])
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text("系列：天地大道\n原音频：demo.mp3\n状态：待复核\n\n---\n\n正文内容。", encoding="utf-8")
        (pipeline_dir / "manifest.json").write_text(
            json.dumps({"entries": {"tiandi/关系底牌": entry}}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return workspace

    def test_main_uses_stable_sequence_as_issue_number_and_injects_principles(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = self._prepare_workspace(
                tmp,
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_name": "20260328. 关系底牌 [abc123].mp3",
                    "sequence": 3,
                    "display_title": "关系底牌",
                    "transcript_path": str(Path(tmp) / "文稿" / "录音稿" / "天地大道" / "03_关系底牌.md"),
                    "article_status": "pending",
                    "article_paths": [],
                    "review_status": "pending",
                },
            )
            captured = {}

            def fake_generate(
                *,
                client,
                prompt_path,
                issue_number,
                transcript_text,
                principles_text,
                expected_article_count=None,
            ):
                del client, prompt_path, transcript_text, expected_article_count
                captured["issue_number"] = issue_number
                captured["principles_text"] = principles_text
                return [ArticleDraft(title="关系底牌", body="正文")]

            with patch.dict(
                os.environ,
                {
                    "DOCUMENT_ROOT": str(workspace / "文稿"),
                    "ARTICLE_PRINCIPLES_PATH": str(workspace / "文稿" / "本地配置" / "文章拆解核心原则与心法.md"),
                    "EXPECTED_ARTICLES_PER_TRANSCRIPT": "",
                },
                clear=False,
            ), patch(
                "sys.argv",
                ["split_to_wechat_articles.py", "--workspace-root", str(workspace), "--allow-pending-review"],
            ), patch(
                "scripts.split_to_wechat_articles.build_text_client_from_env",
                return_value=object(),
            ), patch("scripts.split_to_wechat_articles.llm_generate_articles", side_effect=fake_generate):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured["issue_number"], "03")
            self.assertIn("文章拆解核心原则", captured["principles_text"])
            manifest = PipelineManifest(workspace / ".pipeline" / "manifest.json")
            manifest.load()
            entry = manifest.get("tiandi/关系底牌")
            self.assertEqual(entry["article_status"], "completed")
            self.assertEqual(
                Path(entry["article_paths"][0]),
                workspace / "文稿" / "拆解文章" / "天地大道" / "03_关系底牌" / "03-01_关系底牌.md",
            )
            self.assertTrue(Path(entry["article_paths"][0]).exists())

    def test_main_repairs_manifest_when_all_article_files_already_exist(self) -> None:
        with TemporaryDirectory() as tmp:
            article_path = Path(tmp) / "文稿" / "拆解文章" / "天地大道" / "03_关系底牌" / "03-01_关系底牌.md"
            article_path.parent.mkdir(parents=True, exist_ok=True)
            article_path.write_text("已存在文章\n", encoding="utf-8")
            workspace = self._prepare_workspace(
                tmp,
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_name": "20260328. 关系底牌 [abc123].mp3",
                    "sequence": 3,
                    "display_title": "关系底牌",
                    "transcript_path": str(Path(tmp) / "文稿" / "录音稿" / "天地大道" / "03_关系底牌.md"),
                    "article_status": "pending",
                    "article_paths": [str(article_path)],
                    "review_status": "pending",
                },
            )

            with patch.dict(
                os.environ,
                {
                    "DOCUMENT_ROOT": str(workspace / "文稿"),
                    "ARTICLE_PRINCIPLES_PATH": str(workspace / "文稿" / "本地配置" / "文章拆解核心原则与心法.md"),
                },
                clear=False,
            ), patch("sys.argv", ["split_to_wechat_articles.py", "--workspace-root", str(workspace)]), patch(
                "scripts.split_to_wechat_articles.build_text_client_from_env",
                side_effect=AssertionError("不应调用 LLM"),
            ):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            manifest = PipelineManifest(workspace / ".pipeline" / "manifest.json")
            manifest.load()
            entry = manifest.get("tiandi/关系底牌")
            self.assertEqual(entry["article_status"], "completed")
            self.assertEqual(entry["article_paths"], [str(article_path)])

    def test_main_marks_failed_when_article_paths_are_partially_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            existing_path = Path(tmp) / "文稿" / "拆解文章" / "天地大道" / "03_关系底牌" / "03-01_关系底牌.md"
            missing_path = Path(tmp) / "文稿" / "拆解文章" / "天地大道" / "03_关系底牌" / "03-02_第二篇.md"
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_text("已存在文章\n", encoding="utf-8")
            workspace = self._prepare_workspace(
                tmp,
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_name": "20260328. 关系底牌 [abc123].mp3",
                    "sequence": 3,
                    "display_title": "关系底牌",
                    "transcript_path": str(Path(tmp) / "文稿" / "录音稿" / "天地大道" / "03_关系底牌.md"),
                    "article_status": "completed",
                    "article_paths": [str(existing_path), str(missing_path)],
                    "review_status": "reviewed",
                },
            )

            with patch.dict(
                os.environ,
                {
                    "DOCUMENT_ROOT": str(workspace / "文稿"),
                    "ARTICLE_PRINCIPLES_PATH": str(workspace / "文稿" / "本地配置" / "文章拆解核心原则与心法.md"),
                    "EXPECTED_ARTICLES_PER_TRANSCRIPT": "",
                },
                clear=False,
            ), patch("sys.argv", ["split_to_wechat_articles.py", "--workspace-root", str(workspace)]), patch(
                "scripts.split_to_wechat_articles.build_text_client_from_env",
                return_value=object(),
            ), patch(
                "scripts.split_to_wechat_articles.llm_generate_articles",
                return_value=[ArticleDraft(title="关系底牌", body="新的正文")],
            ):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            manifest = PipelineManifest(workspace / ".pipeline" / "manifest.json")
            manifest.load()
            entry = manifest.get("tiandi/关系底牌")
            self.assertEqual(entry["article_status"], "completed")
            self.assertTrue(Path(entry["article_paths"][0]).exists())
            self.assertTrue((workspace / ".pipeline" / "recovery" / "articles").exists())

    def test_main_fails_when_article_count_mismatch_with_expected(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = self._prepare_workspace(
                tmp,
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_name": "20260328. 关系底牌 [abc123].mp3",
                    "sequence": 3,
                    "display_title": "关系底牌",
                    "transcript_path": str(Path(tmp) / "文稿" / "录音稿" / "天地大道" / "03_关系底牌.md"),
                    "article_status": "pending",
                    "article_paths": [],
                    "review_status": "reviewed",
                },
            )
            call_count = {"n": 0}

            def fake_generate(*, client, prompt_path, issue_number, transcript_text, principles_text, expected_article_count=None):
                del client, prompt_path, transcript_text, principles_text, expected_article_count
                call_count["n"] += 1
                return [ArticleDraft(title="仅一篇", body="正文")]

            with patch.dict(
                os.environ,
                {
                    "DOCUMENT_ROOT": str(workspace / "文稿"),
                    "ARTICLE_PRINCIPLES_PATH": str(workspace / "文稿" / "本地配置" / "文章拆解核心原则与心法.md"),
                },
                clear=False,
            ), patch(
                "sys.argv",
                [
                    "split_to_wechat_articles.py",
                    "--workspace-root",
                    str(workspace),
                    "--expected-articles",
                    "14",
                ],
            ), patch(
                "scripts.split_to_wechat_articles.build_text_client_from_env",
                return_value=object(),
            ), patch("scripts.split_to_wechat_articles.llm_generate_articles", side_effect=fake_generate):
                exit_code = main()

            self.assertEqual(exit_code, 2)
            manifest = PipelineManifest(workspace / ".pipeline" / "manifest.json")
            manifest.load()
            self.assertEqual(manifest.get("tiandi/关系底牌")["article_status"], "failed")
            self.assertEqual(call_count["n"], 3)

    def test_main_archives_disk_only_residual_articles_before_regenerating(self) -> None:
        with TemporaryDirectory() as tmp:
            residual_path = Path(tmp) / "文稿" / "拆解文章" / "天地大道" / "03_关系底牌" / "03-01_旧文章.md"
            residual_path.parent.mkdir(parents=True, exist_ok=True)
            residual_path.write_text("旧稿\n", encoding="utf-8")
            workspace = self._prepare_workspace(
                tmp,
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_name": "20260328. 关系底牌 [abc123].mp3",
                    "sequence": 3,
                    "display_title": "关系底牌",
                    "transcript_path": str(Path(tmp) / "文稿" / "录音稿" / "天地大道" / "03_关系底牌.md"),
                    "article_status": "pending",
                    "article_paths": [],
                    "review_status": "reviewed",
                },
            )

            with patch.dict(
                os.environ,
                {
                    "DOCUMENT_ROOT": str(workspace / "文稿"),
                    "ARTICLE_PRINCIPLES_PATH": str(workspace / "文稿" / "本地配置" / "文章拆解核心原则与心法.md"),
                },
                clear=False,
            ), patch(
                "sys.argv",
                ["split_to_wechat_articles.py", "--workspace-root", str(workspace)],
            ), patch(
                "scripts.split_to_wechat_articles.build_text_client_from_env",
                return_value=object(),
            ), patch(
                "scripts.split_to_wechat_articles.llm_generate_articles",
                return_value=[ArticleDraft(title="关系底牌", body="正文")],
            ):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            manifest = PipelineManifest(workspace / ".pipeline" / "manifest.json")
            manifest.load()
            entry = manifest.get("tiandi/关系底牌")
            self.assertEqual(entry["article_status"], "completed")
            self.assertTrue(Path(entry["article_paths"][0]).exists())
            self.assertTrue((workspace / ".pipeline" / "recovery" / "articles").exists())

    def test_main_returns_nonzero_when_principles_file_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = self._prepare_workspace(
                tmp,
                {
                    "status": "completed",
                    "series_key": "tiandi",
                    "source_name": "20260328. 关系底牌 [abc123].mp3",
                    "sequence": 3,
                    "display_title": "关系底牌",
                    "transcript_path": str(Path(tmp) / "文稿" / "录音稿" / "天地大道" / "03_关系底牌.md"),
                    "article_status": "pending",
                    "article_paths": [],
                    "review_status": "pending",
                },
            )
            (workspace / "文稿" / "本地配置" / "文章拆解核心原则与心法.md").unlink()

            with patch.dict(
                os.environ,
                {
                    "DOCUMENT_ROOT": str(workspace / "文稿"),
                    "ARTICLE_PRINCIPLES_PATH": str(workspace / "文稿" / "本地配置" / "文章拆解核心原则与心法.md"),
                },
                clear=False,
            ), patch("sys.argv", ["split_to_wechat_articles.py", "--workspace-root", str(workspace)]), patch(
                "scripts.split_to_wechat_articles.build_text_client_from_env",
                side_effect=AssertionError("不应调用 LLM"),
            ):
                exit_code = main()

            self.assertEqual(exit_code, 2)

    def test_main_exits_when_expected_articles_env_is_invalid(self) -> None:
        with patch.dict(
            os.environ,
            {"EXPECTED_ARTICLES_PER_TRANSCRIPT": "invalid"},
            clear=False,
        ), patch("sys.argv", ["split_to_wechat_articles.py"]):
            with self.assertRaises(SystemExit) as ctx:
                main()

        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
