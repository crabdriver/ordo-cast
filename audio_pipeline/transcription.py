from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import request


ASSEMBLYAI_BASE_URL = "https://api.assemblyai.com/v2"


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
        with request.urlopen(req) as response:
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
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))

