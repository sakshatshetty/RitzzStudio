import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from modules.voice.alignment import build_alignment
from modules.voice.audio import probe_audio_duration
from modules.voice.models import (
    VoiceAlignment,
    VoiceGenerationRequest,
    VoiceGenerationResult,
)


class RemonaProvider:
    """Generate preset-voice narration through Remona's asynchronous TTS API."""

    BASE_URL = "https://remona.net"
    MODEL_ID = "eleven_multilingual_v2"
    TASK_TIMEOUT_SECONDS = 1800
    POLL_INTERVAL_SECONDS = 5
    retry_on_alignment_error = False

    def __init__(
        self,
        api_key: str | None = None,
        voice_preset: str | None = None,
        *,
        alignment_python: str | None = None,
    ) -> None:
        self.api_key = (api_key or os.getenv("REMONA_API_KEY", "")).strip()
        self.voice_preset = (
            voice_preset or os.getenv("REMONA_VOICE_PRESET", "")
        ).strip()
        self.alignment_python = (
            alignment_python
            or os.environ.get("RITZZ_WHISPERX_PYTHON")
            or sys.executable
        )
        if not self.api_key:
            raise ValueError("REMONA_API_KEY is not configured.")
        if not self.voice_preset:
            raise ValueError("REMONA_VOICE_PRESET is not configured.")

    def generate(
        self,
        request: VoiceGenerationRequest,
    ) -> VoiceGenerationResult:
        if request.model_id != self.MODEL_ID:
            raise ValueError(
                f"RemonaProvider only supports the {self.MODEL_ID} model."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            f"{self.BASE_URL}/runwayml/v1/text_to_speech",
            headers=headers,
            json={
                "model": self.MODEL_ID,
                "promptText": request.text,
                "voice": {
                    "type": "runway-preset",
                    "presetId": self.voice_preset,
                },
            },
            timeout=60,
        )
        self._raise_for_status(response)
        submission = self._json_object(response, "Remona task submission")
        task_id = submission.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Remona task submission did not return an id.")

        audio_url = self._wait_for_audio_url(task_id, headers)
        output_directory = Path(request.output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / request.output_filename

        with tempfile.TemporaryDirectory(
            prefix="remona-",
            dir=output_directory,
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            source_audio = temporary_path / "source-audio"
            audio_response = requests.get(audio_url, timeout=300)
            self._raise_for_status(audio_response)
            if not audio_response.content:
                raise ValueError("Remona returned an empty audio file.")
            source_audio.write_bytes(audio_response.content)

            temporary_mp3 = temporary_path / "narration.mp3"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source_audio),
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(temporary_mp3),
                ],
                check=True,
            )
            duration = float(probe_audio_duration(temporary_mp3))
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(
                    "Remona audio has a non-positive or invalid duration."
                )
            alignment = self._align_audio(
                temporary_mp3,
                request.text,
                duration,
                temporary_path,
            )
            temporary_mp3.replace(output_path)

        return VoiceGenerationResult(
            voice_id=f"remona-preset:{self.voice_preset}",
            model_id=self.MODEL_ID,
            status="completed",
            file_path=str(output_path),
            duration_seconds=duration,
            character_count=len(request.text),
            alignment=alignment,
        )

    def _wait_for_audio_url(
        self,
        task_id: str,
        headers: dict[str, str],
    ) -> str:
        deadline = time.monotonic() + self.TASK_TIMEOUT_SECONDS
        task_url = f"{self.BASE_URL}/runwayml/v1/tasks/{task_id}"
        while True:
            response = requests.get(
                task_url,
                headers=headers,
                timeout=60,
            )
            self._raise_for_status(response)
            task = self._json_object(response, "Remona task status")
            status = str(task.get("status", "")).casefold()
            if status in {"failed", "error", "cancelled", "canceled"}:
                detail = task.get("error") or task.get("message") or status
                raise RuntimeError(f"Remona narration task failed: {detail}")

            audio_url = self._find_audio_url(task.get("output"))
            if audio_url is not None:
                return audio_url
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Remona narration task {task_id} did not finish within "
                    f"{self.TASK_TIMEOUT_SECONDS} seconds."
                )
            time.sleep(self.POLL_INTERVAL_SECONDS)

    def _align_audio(
        self,
        audio_file: Path,
        text: str,
        duration_seconds: float,
        temporary_path: Path,
    ) -> VoiceAlignment:
        input_chunk = {
            "audio_file": str(audio_file),
            "audio_offset_seconds": 0.0,
            "duration_seconds": duration_seconds,
            "end_character": len(text),
            "start_character": 0,
            "text": text,
        }
        alignment_input = temporary_path / "alignment-input.json"
        alignment_output = temporary_path / "alignment-output.json"
        alignment_input.write_text(
            json.dumps({"chunks": [input_chunk]}, ensure_ascii=False),
            encoding="utf-8",
        )
        aligner_script = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "align_voice_chunks.py"
        )
        subprocess.run(
            [
                self.alignment_python,
                str(aligner_script),
                "--input",
                str(alignment_input),
                "--output",
                str(alignment_output),
            ],
            check=True,
        )
        aligned_chunks = self._json_object_from_file(
            alignment_output,
            "WhisperX alignment",
        ).get("chunks")
        if not isinstance(aligned_chunks, list):
            raise TypeError("WhisperX did not return aligned audio chunks.")
        return build_alignment(
            text,
            [input_chunk],
            aligned_chunks,
            duration_seconds,
        )

    @staticmethod
    def _json_object(response: Any, description: str) -> dict[str, Any]:
        data = response.json()
        if not isinstance(data, dict):
            raise TypeError(f"{description} response must be a JSON object.")
        return data

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            if response.status_code == 402:
                raise RuntimeError(
                    "Remona returned HTTP 402 payment_required. Activate a "
                    "Coder package or add credits in the Remona console."
                ) from error
            if response.status_code == 403:
                raise RuntimeError(
                    "Remona denied access to this model (HTTP 403). Check the "
                    "account's model plan or top up credits."
                ) from error
            raise

    @staticmethod
    def _json_object_from_file(path: Path, description: str) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError(f"{description} must be a JSON object.")
        return data

    @classmethod
    def _find_audio_url(cls, value: Any) -> str | None:
        if isinstance(value, str):
            parsed = urlparse(value)
            return value if parsed.scheme == "https" and parsed.netloc else None
        if isinstance(value, list):
            for item in value:
                audio_url = cls._find_audio_url(item)
                if audio_url is not None:
                    return audio_url
            return None
        if isinstance(value, dict):
            for key in ("audio_url", "url", "audio", "outputs"):
                if key in value:
                    audio_url = cls._find_audio_url(value[key])
                    if audio_url is not None:
                        return audio_url
        return None
