from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Callable, Dict, Optional, Tuple
import uuid
from urllib import request

from .config import extract_sequence_prefix
from .hashing import sha1_file

HTTP_DEFAULT_TIMEOUT = 60.0


ASSEMBLYAI_BASE_URL = "https://api.assemblyai.com/v2"
VOLC_BIGMODEL_SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
VOLC_BIGMODEL_QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
VOLC_BIGMODEL_IDLE_SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/idle/submit"
VOLC_BIGMODEL_IDLE_QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/idle/query"
AUTH_HINT_KEYWORDS = (
    "access token",
    "token",
    "auth",
    "accessdenied",
    "invalidaccesskeyid",
    "signaturedoesnotmatch",
    "forbidden",
    "unauthorized",
)
TRANSIENT_ERROR_KEYWORDS = (
    "connection reset by peer",
    "connection aborted",
    "requesterror",
    "timed out",
    "temporarily unavailable",
    "eof occurred in violation of protocol",
)


@dataclass(frozen=True)
class TranscriptionJobState:
    status: str
    text: Optional[str]
    error_message: Optional[str]


class AbstractTranscriptionProvider(ABC):
    @abstractmethod
    def submit(self, audio_path: Path) -> str:
        raise NotImplementedError

    @abstractmethod
    def poll(self, job_id: str) -> TranscriptionJobState:
        raise NotImplementedError


class AbstractAudioUploader(ABC):
    @abstractmethod
    def upload(self, audio_path: Path) -> str:
        raise NotImplementedError


class AliyunOssSignedUploader(AbstractAudioUploader):
    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        bucket_name: str,
        endpoint: str,
        key_prefix: str = "audio-source",
        expires: int = 3600,
        storage_class: str = "Standard",
        bucket: Any = None,
        max_retries: int = 3,
        retry_sleep_seconds: float = 1.0,
    ) -> None:
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.bucket_name = bucket_name
        self.endpoint = endpoint
        self.key_prefix = key_prefix.strip("/")
        self.expires = expires
        self.storage_class = storage_class
        self._bucket = bucket
        self.max_retries = max(1, max_retries)
        self.retry_sleep_seconds = retry_sleep_seconds

    def upload(self, audio_path: Path) -> str:
        object_key = self._build_object_key(audio_path)
        bucket = self._get_bucket()
        for attempt in range(1, self.max_retries + 1):
            try:
                bucket.put_object_from_file(
                    object_key,
                    str(audio_path),
                    headers=self._upload_headers(forbid_overwrite=True),
                )
                return bucket.sign_url("GET", object_key, self.expires, slash_safe=True)
            except Exception as exc:
                detail = str(exc)
                if _is_existing_object_error(detail):
                    if self._object_is_readable(bucket, object_key):
                        return bucket.sign_url("GET", object_key, self.expires, slash_safe=True)
                    bucket.put_object_from_file(
                        object_key,
                        str(audio_path),
                        headers=self._upload_headers(forbid_overwrite=False),
                    )
                    return bucket.sign_url("GET", object_key, self.expires, slash_safe=True)
                if not _is_transient_error(detail) or attempt >= self.max_retries:
                    raise RuntimeError(_format_auth_aware_error("OSS", detail, "请检查 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET 是否已失效。")) from exc
                if self.retry_sleep_seconds > 0:
                    time.sleep(self.retry_sleep_seconds)
        raise RuntimeError("OSS 调用失败：上传未完成")

    def _upload_headers(self, *, forbid_overwrite: bool) -> dict[str, str]:
        headers = {"x-oss-storage-class": self.storage_class}
        if forbid_overwrite:
            headers["x-oss-forbid-overwrite"] = "true"
        return headers

    def _object_is_readable(self, bucket: Any, object_key: str) -> bool:
        try:
            response = bucket.get_object(object_key)
            try:
                response.read(1)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            return True
        except Exception:
            return False

    def _build_object_key(self, audio_path: Path) -> str:
        parts = [part for part in [self.key_prefix, audio_path.parent.name, self._build_object_filename(audio_path)] if part]
        return "/".join(parts)

    def _build_object_filename(self, audio_path: Path) -> str:
        sequence = extract_sequence_prefix(audio_path.name) or 0
        digest = sha1_file(audio_path)[:16]
        suffix = audio_path.suffix.lower() or ".mp3"
        return f"{sequence:04d}_{digest}{suffix}"

    def _get_bucket(self) -> Any:
        if self._bucket is not None:
            return self._bucket
        try:
            import oss2
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("请先安装 oss2：pip install oss2") from exc

        auth = oss2.Auth(self.access_key_id, self.access_key_secret)
        self._bucket = oss2.Bucket(auth, f"https://{self.endpoint}", self.bucket_name)
        return self._bucket


class AssemblyAITranscriptionProvider(AbstractTranscriptionProvider):
    def __init__(self, api_key: str, language_code: str = "zh") -> None:
        self.api_key = api_key
        self.language_code = language_code

    def submit(self, audio_path: Path) -> str:
        upload_url = self._upload_file(audio_path)
        payload = {
            "audio_url": upload_url,
            "language_code": self.language_code,
            "speaker_labels": False,
            "punctuate": True,
            "format_text": True,
        }
        response = self._request_json(
            method="POST",
            url=f"{ASSEMBLYAI_BASE_URL}/transcript",
            json_payload=payload,
        )
        return response["id"]

    def poll(self, job_id: str) -> TranscriptionJobState:
        response = self._request_json(
            method="GET",
            url=f"{ASSEMBLYAI_BASE_URL}/transcript/{job_id}",
        )
        status = response.get("status", "unknown")
        if status == "completed":
            return TranscriptionJobState(status=status, text=response.get("text", ""), error_message=None)
        if status == "error":
            return TranscriptionJobState(
                status=status,
                text=None,
                error_message=response.get("error", "未知转录错误"),
            )
        return TranscriptionJobState(status=status, text=None, error_message=None)

    def _upload_file(self, audio_path: Path) -> str:
        url = f"{ASSEMBLYAI_BASE_URL}/upload"
        data = audio_path.read_bytes()
        req = request.Request(
            url=url,
            data=data,
            method="POST",
            headers={"authorization": self.api_key, "content-type": "application/octet-stream"},
        )
        with request.urlopen(req, timeout=HTTP_DEFAULT_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["upload_url"]

    def _request_json(
        self,
        *,
        method: str,
        url: str,
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data = None
        headers = {"authorization": self.api_key}
        if json_payload is not None:
            data = json.dumps(json_payload).encode("utf-8")
            headers["content-type"] = "application/json"
        req = request.Request(url=url, data=data, method=method, headers=headers)
        with request.urlopen(req, timeout=HTTP_DEFAULT_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))


class VolcengineBigModelProvider(AbstractTranscriptionProvider):
    submit_url = VOLC_BIGMODEL_SUBMIT_URL
    query_url = VOLC_BIGMODEL_QUERY_URL

    def __init__(
        self,
        *,
        app_key: str,
        access_key: str,
        resource_id: str,
        uploader: Callable[[Path], str],
        api_mode: str = "standard",
        language: str = "zh-CN",
        request_client: Optional[Callable[..., Tuple[Dict[str, Any], Dict[str, str]]]] = None,
        uid_provider: Optional[Callable[[], str]] = None,
        request_id_provider: Optional[Callable[[], str]] = None,
    ) -> None:
        self.app_key = app_key
        self.access_key = access_key
        self.resource_id = resource_id
        self.uploader = uploader
        self.api_mode = api_mode
        self.language = language
        self.request_client = request_client or self._post_json
        self.uid_provider = uid_provider or (lambda: str(uuid.uuid4()))
        self.request_id_provider = request_id_provider or (lambda: str(uuid.uuid4()))
        self.submit_url, self.query_url = _resolve_volcengine_urls(api_mode)

    def submit(self, audio_path: Path) -> str:
        request_id = self.request_id_provider()
        audio_url = self.uploader(audio_path)
        _, headers = self.request_client(
            url=self.submit_url,
            headers=self._headers(request_id),
            json_payload={
                "user": {"uid": self.uid_provider()},
                "audio": {
                    "url": audio_url,
                    "format": audio_path.suffix.lstrip(".").lower() or "mp3",
                    "language": self.language,
                },
                "request": {
                    "model_name": "bigmodel",
                    "enable_itn": True,
                    "enable_punc": True,
                    "enable_ddc": True,
                    "show_utterances": True,
                },
            },
        )
        self._ensure_success(headers, request_id)
        return request_id

    def poll(self, job_id: str) -> TranscriptionJobState:
        body, headers = self.request_client(
            url=self.query_url,
            headers=self._headers(job_id),
            json_payload={},
        )
        status_code = headers.get("X-Api-Status-Code", "")
        message = headers.get("X-Api-Message", "")
        if status_code == "20000000":
            result = body.get("result", {})
            return TranscriptionJobState(status="completed", text=result.get("text", ""), error_message=None)
        if status_code in {"20000001", "20000002"}:
            return TranscriptionJobState(status="processing", text=None, error_message=None)
        return TranscriptionJobState(
            status="error",
            text=None,
            error_message=f"{status_code}: {message or '火山转录失败'}",
        )

    def _headers(self, request_id: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }

    def _ensure_success(self, headers: Dict[str, str], request_id: str) -> None:
        status_code = headers.get("X-Api-Status-Code", "")
        message = headers.get("X-Api-Message", "")
        if status_code != "20000000":
            detail = f"{status_code} {message}".strip()
            raise RuntimeError(_format_auth_aware_error("火山 ASR", detail, "请检查 VOLCENGINE_ACCESS_TOKEN / VOLCENGINE_APP_KEY 是否已失效。"))

    def _post_json(self, *, url: str, headers: Dict[str, str], json_payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
        req = request.Request(
            url=url,
            data=json.dumps(json_payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with request.urlopen(req, timeout=HTTP_DEFAULT_TIMEOUT) as response:
                raw_headers = {key: value for key, value in response.headers.items()}
                raw_body = response.read().decode("utf-8").strip()
                body = json.loads(raw_body) if raw_body else {}
                return body, raw_headers
        except Exception as exc:
            raise RuntimeError(_format_auth_aware_error("火山 ASR", str(exc), "请检查 VOLCENGINE_ACCESS_TOKEN / VOLCENGINE_APP_KEY 是否已失效。")) from exc


def _format_auth_aware_error(service_name: str, detail: str, hint: str) -> str:
    lowered = detail.lower()
    if any(keyword in lowered for keyword in AUTH_HINT_KEYWORDS):
        return f"{service_name} 鉴权失败，{hint} 原始错误：{detail}"
    return f"{service_name} 调用失败：{detail}"


def _is_transient_error(detail: str) -> bool:
    lowered = detail.lower()
    return any(keyword in lowered for keyword in TRANSIENT_ERROR_KEYWORDS)


def _is_existing_object_error(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        keyword in lowered
        for keyword in (
            "filealreadyexists",
            "already exists",
            "object already exists",
            "forbid-overwrite",
        )
    )


def _resolve_volcengine_urls(api_mode: str) -> tuple[str, str]:
    if api_mode == "idle":
        return VOLC_BIGMODEL_IDLE_SUBMIT_URL, VOLC_BIGMODEL_IDLE_QUERY_URL
    return VOLC_BIGMODEL_SUBMIT_URL, VOLC_BIGMODEL_QUERY_URL

