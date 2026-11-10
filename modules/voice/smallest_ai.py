"""Smallest AI Lightning text-to-speech provider."""

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

from modules.voice.alignment import build_alignment
from modules.voice.audio import probe_audio_duration
from modules.voice.models import (
    VoiceAlignment,
    VoiceGenerationRequest,
    VoiceGenerationResult,
)

SMALLEST_LIGHTNING_MODELS = frozenset(
    {"lightning_v3.1", "lightning_v3.1_pro"}
)


class SmallestAIProvider:
    """Generate Lightning TTS narration and align it with WhisperX."""

    BASE_URL = "https://api.smallest.ai/waves/v1"
    SUPPORTED_MODELS = SMALLEST_LIGHTNING_MODELS
    MAX_INPUT_CHARACTERS = 250
    retry_on_alignment_error = False

    def __init__(
        self,
        api_key: str | None = None,
        *,
        language: str | None = None,
        alignment_python: str | None = None,
    ) -> None:
        configured_key = (
            api_key if api_key is not None else os.getenv("SMALLEST_API_KEY", "")
        )
        self.api_key = configured_key.strip()
        self.language = (
            language or os.getenv("SMALLEST_LANGUAGE", "en")
        ).strip()
        self.alignment_python = (
            alignment_python
            or os.environ.get("RITZZ_WHISPERX_PYTHON")
            or sys.executable
        )
        if not self.api_key:
            raise ValueError("SMALLEST_API_KEY is not configured.")
        if not self.language:
            raise ValueError("SMALLEST_LANGUAGE is not configured.")

    def generate(
        self,
        request: VoiceGenerationRequest,
    ) -> VoiceGenerationResult:
        if request.model_id not in self.SUPPORTED_MODELS:
            supported = ", ".join(sorted(self.SUPPORTED_MODELS))
            raise ValueError(
                f"SmallestAIProvider supports only these models: {supported}."
            )

        output_directory = Path(request.output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / request.output_filename

        with tempfile.TemporaryDirectory(
            prefix="smallest-ai-",
            dir=output_directory,
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            part_files: list[Path] = []
            text_chunks = self._split_text(request.text)
            for index, text_chunk in enumerate(text_chunks):
                response = requests.post(
                    f"{self.BASE_URL}/tts",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "audio/wav",
                    },
                    json={
                        "text": text_chunk,
                        "voice_id": request.voice_id,
                        "model": request.model_id,
                        "sample_rate": 24000,
                        "speed": request.voice_settings.speed,
                        "language": self.language,
                        "output_format": "wav",
                    },
                    timeout=300,
                )
                response.raise_for_status()
                audio_bytes = response.content
                if (
                    len(audio_bytes) < 12
                    or audio_bytes[:4] != b"RIFF"
                    or audio_bytes[8:12] != b"WAVE"
                ):
                    raise ValueError(
                        "Smallest AI did not return a valid WAV audio response."
                    )
                part_path = temporary_path / f"part-{index:04d}.wav"
                part_path.write_bytes(audio_bytes)
                part_files.append(part_path)

            concat_file = temporary_path / "parts.ffconcat"
            concat_file.write_text(
                "ffconcat version 1.0\n"
                + "".join(f"file '{path.name}'\n" for path in part_files),
                encoding="utf-8",
            )
            temporary_mp3 = temporary_path / "narration.mp3"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(temporary_mp3),
                ],
                cwd=temporary_path,
                check=True,
            )
            duration = float(probe_audio_duration(temporary_mp3))
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(
                    "Smallest AI audio has a non-positive or invalid duration."
                )
            alignment_chunks: list[dict[str, Any]] = []
            audio_offset = 0.0
            character_offset = 0
            for text_chunk, part_path in zip(
                text_chunks,
                part_files,
                strict=True,
            ):
                chunk_duration = float(probe_audio_duration(part_path))
                alignment_chunks.append(
                    {
                        "audio_file": str(part_path),
                        "audio_offset_seconds": audio_offset,
                        "duration_seconds": chunk_duration,
                        "end_character": character_offset + len(text_chunk),
                        "start_character": character_offset,
                        "text": text_chunk,
                    }
                )
                audio_offset += chunk_duration
                character_offset += len(text_chunk)
            if character_offset != len(request.text):
                raise ValueError(
                    "Smallest AI text chunks do not cover the supplied narration."
                )
            alignment = self._align_audio(
                alignment_chunks,
                request.text,
                duration,
                temporary_path,
            )
            temporary_mp3.replace(output_path)

        return VoiceGenerationResult(
            voice_id=request.voice_id,
            model_id=request.model_id,
            status="completed",
            file_path=str(output_path),
            duration_seconds=duration,
            character_count=len(request.text),
            alignment=alignment,
        )

    @classmethod
    def _split_text(cls, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            window_end = min(start + cls.MAX_INPUT_CHARACTERS, len(text))
            if window_end == len(text):
                chunks.append(text[start:])
                break

            window = text[start:window_end]
            sentence_end = max(
                (window.rfind(mark) for mark in ".!?"),
                default=-1,
            )
            if sentence_end >= cls.MAX_INPUT_CHARACTERS // 2:
                end = start + sentence_end + 1
            else:
                whitespace_end = max(
                    (
                        index
                        for index, character in enumerate(window)
                        if character.isspace()
                    ),
                    default=-1,
                )
                end = (
                    start + whitespace_end + 1
                    if whitespace_end > 0
                    else window_end
                )
            chunks.append(text[start:end])
            start = end
        return chunks

    def _align_audio(
        self,
        input_chunks: list[dict[str, Any]],
        text: str,
        duration_seconds: float,
        temporary_path: Path,
    ) -> VoiceAlignment:
        alignment_input = temporary_path / "alignment-input.json"
        alignment_output = temporary_path / "alignment-output.json"
        alignment_input.write_text(
            json.dumps({"chunks": input_chunks}, ensure_ascii=False),
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
        aligned_chunks = self._read_alignment_chunks(alignment_output)
        return build_alignment(
            text,
            input_chunks,
            aligned_chunks,
            duration_seconds,
        )

    @staticmethod
    def _read_alignment_chunks(
        alignment_output: Path,
    ) -> list[dict[str, Any]]:
        try:
            payload = json.loads(alignment_output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                "WhisperX alignment output is missing or invalid JSON."
            ) from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("chunks"), list
        ):
            raise TypeError("WhisperX did not return aligned audio chunks.")
        return payload["chunks"]
