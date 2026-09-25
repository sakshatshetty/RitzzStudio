import base64
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from modules.voice.models import (
    VoiceAlignment,
    VoiceGenerationRequest,
    VoiceGenerationResult,
)


load_dotenv()


class ElevenLabsProvider:
    """ElevenLabs implementation of the Ritzz VoiceProvider."""

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(
        self,
        api_key: str | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("ELEVENLABS_API_KEY")
        )

        if not self.api_key:
            raise ValueError(
                "ELEVENLABS_API_KEY is not configured."
            )

    def generate(
        self,
        request: VoiceGenerationRequest,
    ) -> VoiceGenerationResult:
        """Generate narration using ElevenLabs."""

        url = (
            f"{self.BASE_URL}/text-to-speech/"
            f"{request.voice_id}/with-timestamps"
        )

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "text": request.text,
            "model_id": request.model_id,
            "output_format": request.output_format,
        }
        payload["voice_settings"] = request.voice_settings.model_dump()

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=300,
            )

            response.raise_for_status()

            data: dict[str, Any] = response.json()

            audio_base64 = data.get(
                "audio_base64"
            )

            if not audio_base64:
                raise ValueError(
                    "ElevenLabs response did not contain audio_base64."
                )

            try:
                audio_bytes = base64.b64decode(
                    audio_base64,
                    validate=True,
                )
            except Exception as exc:
                raise ValueError(
                    "ElevenLabs returned invalid Base64 audio."
                ) from exc

            if not audio_bytes:
                raise ValueError(
                    "ElevenLabs returned empty audio."
                )

            output_directory = Path(
                request.output_directory
            )

            output_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            output_path = (
                output_directory
                / request.output_filename
            )

            output_path.write_bytes(
                audio_bytes
            )

            alignment = self._parse_alignment(
                data.get("alignment")
            )

            duration = self._estimate_duration(
                alignment
            )

            return VoiceGenerationResult(
                voice_id=request.voice_id,
                model_id=request.model_id,
                status="completed",
                file_path=str(output_path),
                duration_seconds=duration,
                character_count=len(request.text),
                alignment=alignment,
            )

        except requests.HTTPError as exc:
            return VoiceGenerationResult(
                voice_id=request.voice_id,
                model_id=request.model_id,
                status="failed",
                error_message=self._format_http_error(
                    exc
                ),
            )

        except Exception as exc:
            return VoiceGenerationResult(
                voice_id=request.voice_id,
                model_id=request.model_id,
                status="failed",
                error_message=str(exc),
            )

    @staticmethod
    def _parse_alignment(
        alignment_data: Any,
    ) -> VoiceAlignment | None:
        """Convert ElevenLabs alignment data to Ritzz alignment."""

        if not alignment_data:
            return None

        characters = alignment_data.get(
            "characters",
            [],
        )

        start_times = alignment_data.get(
            "character_start_times_seconds",
            [],
        )

        end_times = alignment_data.get(
            "character_end_times_seconds",
            [],
        )

        if not (
            characters
            and start_times
            and end_times
        ):
            return None

        if not (
            len(characters)
            == len(start_times)
            == len(end_times)
        ):
            raise ValueError(
                "ElevenLabs alignment arrays have different lengths."
            )

        return VoiceAlignment(
            characters=characters,
            character_start_times_seconds=start_times,
            character_end_times_seconds=end_times,
        )

    @staticmethod
    def _estimate_duration(
        alignment: VoiceAlignment | None,
    ) -> float | None:
        """Estimate duration from the final character timestamp."""

        if not alignment:
            return None

        if not alignment.character_end_times_seconds:
            return None

        return max(
            alignment.character_end_times_seconds
        )

    @staticmethod
    def _format_http_error(
        error: requests.HTTPError,
    ) -> str:
        """Return a useful and safe API error message."""

        response = error.response

        if response is None:
            return str(error)

        try:
            data = response.json()

            detail = data.get(
                "detail"
            )

            if isinstance(detail, dict):
                message = detail.get(
                    "message"
                )

                if message:
                    return str(message)

            if isinstance(detail, str):
                return detail

        except ValueError:
            pass

        return (
            f"ElevenLabs API request failed "
            f"with HTTP {response.status_code}."
        )
