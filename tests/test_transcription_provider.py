from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from audio_pipeline.transcription import AliyunOssSignedUploader, VolcengineBigModelProvider


class VolcengineBigModelProviderTests(unittest.TestCase):
    def test_oss_uploader_uses_different_object_keys_for_same_filename_with_new_content(self) -> None:
        events = {"puts": []}

        class FakeBucket:
            def put_object_from_file(self, object_key, filename, headers=None):
                events["puts"].append((object_key, filename, headers))

            def sign_url(self, method, object_key, expires, headers=None, params=None, slash_safe=False, additional_headers=None):
                return f"https://example.com/{object_key}?signature=1"

        with TemporaryDirectory() as tmp:
            series_dir = Path(tmp) / "天地大道"
            series_dir.mkdir()
            audio_path = series_dir / "01. 第一讲.mp3"
            uploader = AliyunOssSignedUploader(
                access_key_id="oss-ak",
                access_key_secret="oss-sk",
                bucket_name="dianliangxingkong",
                endpoint="oss-cn-shanghai.aliyuncs.com",
                bucket=FakeBucket(),
                key_prefix="audio-source",
                expires=1800,
            )

            audio_path.write_bytes(b"version-1")
            uploader.upload(audio_path)
            audio_path.write_bytes(b"version-2")
            uploader.upload(audio_path)

        self.assertEqual(len(events["puts"]), 2)
        self.assertNotEqual(events["puts"][0][0], events["puts"][1][0])

    def test_oss_uploader_uses_series_folder_prefix_and_forbid_overwrite(self) -> None:
        events = {}

        class FakeBucket:
            def put_object_from_file(self, object_key, filename, headers=None):
                events["put"] = (object_key, filename, headers)

            def sign_url(self, method, object_key, expires, headers=None, params=None, slash_safe=False, additional_headers=None):
                events["sign"] = (method, object_key, expires, slash_safe)
                return f"https://example.com/{object_key}?signature=1"

        with TemporaryDirectory() as tmp:
            series_dir = Path(tmp) / "天地大道"
            series_dir.mkdir()
            audio_path = series_dir / "demo.mp3"
            audio_path.write_bytes(b"123")
            uploader = AliyunOssSignedUploader(
                access_key_id="oss-ak",
                access_key_secret="oss-sk",
                bucket_name="dianliangxingkong",
                endpoint="oss-cn-shanghai.aliyuncs.com",
                bucket=FakeBucket(),
                key_prefix="audio-source",
                expires=1800,
            )

            signed_url = uploader.upload(audio_path)

        self.assertRegex(events["put"][0], r"^audio-source/天地大道/0000_[0-9a-f]{16}\.mp3$")
        self.assertEqual(events["put"][2]["x-oss-forbid-overwrite"], "true")
        self.assertEqual(events["put"][2]["x-oss-storage-class"], "Standard")
        self.assertEqual(events["sign"], ("GET", events["put"][0], 1800, True))
        self.assertTrue(signed_url.startswith(f"https://example.com/{events['put'][0]}"))

    def test_oss_uploader_reuses_existing_object_when_overwrite_forbidden(self) -> None:
        events = {}

        class FakeBucket:
            def put_object_from_file(self, object_key, filename, headers=None):
                events["put"] = (object_key, filename, headers)
                raise RuntimeError("FileAlreadyExists")

            def get_object(self, object_key):
                events["get"] = object_key

                class Response:
                    def read(self, size=-1):
                        return b"x"

                    def close(self):
                        return None

                return Response()

            def sign_url(self, method, object_key, expires, headers=None, params=None, slash_safe=False, additional_headers=None):
                events["sign"] = (method, object_key, expires, slash_safe)
                return f"https://example.com/{object_key}?signature=1"

        with TemporaryDirectory() as tmp:
            series_dir = Path(tmp) / "人类说明书"
            series_dir.mkdir()
            audio_path = series_dir / "demo.mp3"
            audio_path.write_bytes(b"123")
            uploader = AliyunOssSignedUploader(
                access_key_id="oss-ak",
                access_key_secret="oss-sk",
                bucket_name="dianliangxingkong",
                endpoint="oss-cn-shanghai.aliyuncs.com",
                bucket=FakeBucket(),
                key_prefix="audio-source",
                expires=1800,
            )

            signed_url = uploader.upload(audio_path)

        self.assertRegex(events["put"][0], r"^audio-source/人类说明书/0000_[0-9a-f]{16}\.mp3$")
        self.assertEqual(events["put"][2]["x-oss-storage-class"], "Standard")
        self.assertEqual(events["get"], events["put"][0])
        self.assertEqual(events["sign"], ("GET", events["put"][0], 1800, True))
        self.assertTrue(signed_url.startswith(f"https://example.com/{events['put'][0]}"))

    def test_oss_uploader_overwrites_existing_unreadable_object_with_standard_storage(self) -> None:
        events = {"puts": []}

        class FakeBucket:
            def put_object_from_file(self, object_key, filename, headers=None):
                events["puts"].append((object_key, filename, headers))
                if len(events["puts"]) == 1:
                    raise RuntimeError("FileAlreadyExists")

            def get_object(self, object_key):
                events["get"] = object_key
                raise RuntimeError("InvalidObjectState")

            def sign_url(self, method, object_key, expires, headers=None, params=None, slash_safe=False, additional_headers=None):
                events["sign"] = (method, object_key, expires, slash_safe)
                return f"https://example.com/{object_key}?signature=1"

        with TemporaryDirectory() as tmp:
            series_dir = Path(tmp) / "人类说明书"
            series_dir.mkdir()
            audio_path = series_dir / "demo.mp3"
            audio_path.write_bytes(b"123")
            uploader = AliyunOssSignedUploader(
                access_key_id="oss-ak",
                access_key_secret="oss-sk",
                bucket_name="dianliangxingkong",
                endpoint="oss-cn-shanghai.aliyuncs.com",
                bucket=FakeBucket(),
                key_prefix="audio-source",
                expires=1800,
            )

            signed_url = uploader.upload(audio_path)

        self.assertEqual(len(events["puts"]), 2)
        self.assertEqual(events["get"], events["puts"][0][0])
        self.assertEqual(events["puts"][0][2]["x-oss-forbid-overwrite"], "true")
        self.assertEqual(events["puts"][0][2]["x-oss-storage-class"], "Standard")
        self.assertNotIn("x-oss-forbid-overwrite", events["puts"][1][2])
        self.assertEqual(events["puts"][1][2]["x-oss-storage-class"], "Standard")
        self.assertEqual(events["sign"], ("GET", events["puts"][0][0], 1800, True))
        self.assertTrue(signed_url.startswith(f"https://example.com/{events['puts'][0][0]}"))

    def test_idle_mode_uses_idle_submit_and_query_urls(self) -> None:
        provider = VolcengineBigModelProvider(
            app_key="3297659247",
            access_key="token",
            resource_id="volc.bigasr.auc_idle",
            uploader=lambda path: "https://example.com/audio.mp3",
            api_mode="idle",
        )

        self.assertIn("/idle/submit", provider.submit_url)
        self.assertIn("/idle/query", provider.query_url)

    def test_oss_uploader_retries_transient_connection_reset_then_succeeds(self) -> None:
        events = {"attempts": 0}

        class FakeBucket:
            def put_object_from_file(self, object_key, filename, headers=None):
                events["attempts"] += 1
                if events["attempts"] < 3:
                    raise RuntimeError("RequestError: ('Connection aborted.', ConnectionResetError(54, 'Connection reset by peer'))")
                events["put"] = (object_key, filename, headers)

            def sign_url(self, method, object_key, expires, headers=None, params=None, slash_safe=False, additional_headers=None):
                events["sign"] = (method, object_key, expires, slash_safe)
                return f"https://example.com/{object_key}?signature=1"

        with TemporaryDirectory() as tmp:
            series_dir = Path(tmp) / "人类说明书-问道"
            series_dir.mkdir()
            audio_path = series_dir / "demo.mp3"
            audio_path.write_bytes(b"123")
            uploader = AliyunOssSignedUploader(
                access_key_id="oss-ak",
                access_key_secret="oss-sk",
                bucket_name="dianliangxingkong",
                endpoint="oss-cn-shanghai.aliyuncs.com",
                bucket=FakeBucket(),
                key_prefix="audio-source",
                expires=1800,
                max_retries=3,
                retry_sleep_seconds=0,
            )

            signed_url = uploader.upload(audio_path)

        self.assertEqual(events["attempts"], 3)
        self.assertRegex(events["put"][0], r"^audio-source/人类说明书-问道/0000_[0-9a-f]{16}\.mp3$")
        self.assertEqual(events["put"][2]["x-oss-forbid-overwrite"], "true")
        self.assertEqual(events["put"][2]["x-oss-storage-class"], "Standard")
        self.assertEqual(events["sign"], ("GET", events["put"][0], 1800, True))
        self.assertTrue(signed_url.startswith(f"https://example.com/{events['put'][0]}"))

    def test_oss_uploader_uploads_file_and_returns_signed_url(self) -> None:
        events = {}

        class FakeBucket:
            def put_object_from_file(self, object_key, filename, headers=None):
                events["put"] = (object_key, filename, headers)

            def sign_url(self, method, object_key, expires, headers=None, params=None, slash_safe=False, additional_headers=None):
                events["sign"] = (method, object_key, expires, slash_safe)
                return f"https://example.com/{object_key}?signature=1"

        with TemporaryDirectory() as tmp:
            series_dir = Path(tmp) / "天地大道"
            series_dir.mkdir()
            audio_path = series_dir / "demo.mp3"
            audio_path.write_bytes(b"123")
            uploader = AliyunOssSignedUploader(
                access_key_id="oss-ak",
                access_key_secret="oss-sk",
                bucket_name="dianliangxingkong",
                endpoint="oss-cn-shanghai.aliyuncs.com",
                bucket=FakeBucket(),
                key_prefix="audio-source",
                expires=1800,
            )

            signed_url = uploader.upload(audio_path)

        self.assertRegex(events["put"][0], r"^audio-source/天地大道/0000_[0-9a-f]{16}\.mp3$")
        self.assertEqual(events["put"][2]["x-oss-forbid-overwrite"], "true")
        self.assertEqual(events["put"][2]["x-oss-storage-class"], "Standard")
        self.assertEqual(events["sign"], ("GET", events["put"][0], 1800, True))
        self.assertTrue(signed_url.startswith(f"https://example.com/{events['put'][0]}"))

    def test_submit_builds_expected_headers_and_body(self) -> None:
        captured = {}

        def fake_post_json(*, url, headers, json_payload):
            captured["url"] = url
            captured["headers"] = headers
            captured["json_payload"] = json_payload
            return {}, {
                "X-Api-Status-Code": "20000000",
                "X-Api-Message": "OK",
            }

        provider = VolcengineBigModelProvider(
            app_key="3297659247",
            access_key="token",
            resource_id="volc.seedasr.auc",
            uploader=lambda path: "https://example.com/audio.mp3",
            request_client=fake_post_json,
            uid_provider=lambda: "uid-1",
            request_id_provider=lambda: "request-1",
        )

        with TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "demo.mp3"
            audio_path.write_bytes(b"123")
            job_id = provider.submit(audio_path)

        self.assertEqual(job_id, "request-1")
        self.assertEqual(captured["url"], provider.submit_url)
        self.assertEqual(captured["headers"]["X-Api-App-Key"], "3297659247")
        self.assertEqual(captured["headers"]["X-Api-Access-Key"], "token")
        self.assertEqual(captured["headers"]["X-Api-Resource-Id"], "volc.seedasr.auc")
        self.assertEqual(captured["headers"]["X-Api-Request-Id"], "request-1")
        self.assertEqual(captured["json_payload"]["audio"]["url"], "https://example.com/audio.mp3")
        self.assertEqual(captured["json_payload"]["audio"]["format"], "mp3")
        self.assertEqual(captured["json_payload"]["request"]["model_name"], "bigmodel")

    def test_poll_maps_status_code_to_transcription_state(self) -> None:
        responses = [
            (
                {
                    "result": {"text": "转录成功"},
                },
                {
                    "X-Api-Status-Code": "20000000",
                    "X-Api-Message": "OK",
                },
            ),
            (
                {},
                {
                    "X-Api-Status-Code": "20000001",
                    "X-Api-Message": "Processing",
                },
            ),
            (
                {},
                {
                    "X-Api-Status-Code": "45000002",
                    "X-Api-Message": "Empty audio",
                },
            ),
        ]

        def fake_post_json(*, url, headers, json_payload):
            return responses.pop(0)

        provider = VolcengineBigModelProvider(
            app_key="3297659247",
            access_key="token",
            resource_id="volc.seedasr.auc",
            uploader=lambda path: "https://example.com/audio.mp3",
            request_client=fake_post_json,
        )

        completed = provider.poll("job-1")
        processing = provider.poll("job-1")
        failed = provider.poll("job-1")

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.text, "转录成功")
        self.assertEqual(processing.status, "processing")
        self.assertIsNone(processing.text)
        self.assertEqual(failed.status, "error")
        self.assertIn("45000002", failed.error_message)

    def test_submit_raises_clear_message_when_volc_token_expires(self) -> None:
        def fake_post_json(*, url, headers, json_payload):
            return {}, {
                "X-Api-Status-Code": "45000001",
                "X-Api-Message": "Access token expired",
            }

        provider = VolcengineBigModelProvider(
            app_key="3297659247",
            access_key="token",
            resource_id="volc.seedasr.auc",
            uploader=lambda path: "https://example.com/audio.mp3",
            request_client=fake_post_json,
            uid_provider=lambda: "uid-1",
            request_id_provider=lambda: "request-1",
        )

        with TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "demo.mp3"
            audio_path.write_bytes(b"123")
            with self.assertRaises(RuntimeError) as context:
                provider.submit(audio_path)

        self.assertIn("VOLCENGINE_ACCESS_TOKEN", str(context.exception))

    def test_oss_uploader_raises_clear_message_when_key_invalid(self) -> None:
        class FakeBucket:
            def put_object_from_file(self, object_key, filename, headers=None):
                raise RuntimeError("AccessDenied: InvalidAccessKeyId")

        with TemporaryDirectory() as tmp:
            audio_path = Path(tmp) / "demo.mp3"
            audio_path.write_bytes(b"123")
            uploader = AliyunOssSignedUploader(
                access_key_id="oss-ak",
                access_key_secret="oss-sk",
                bucket_name="dianliangxingkong",
                endpoint="oss-cn-shanghai.aliyuncs.com",
                bucket=FakeBucket(),
            )

            with self.assertRaises(RuntimeError) as context:
                uploader.upload(audio_path)

        self.assertIn("OSS_ACCESS_KEY_ID", str(context.exception))


if __name__ == "__main__":
    unittest.main()
