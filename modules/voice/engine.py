import math
import re
from pathlib import Path
from typing import Protocol

from modules.script.models import Script
from modules.project.config import ProductionConfig
from modules.voice.models import (
    VoiceGenerationRequest,
    VoiceGenerationResult,
    VoiceModel,
)
from modules.voice.audio import probe_audio_duration
from modules.voice.text import ensure_terminal_punctuation


class VoiceProvider(Protocol):
    """Interface implemented by a real or mock voice provider."""

    def generate(
        self,
        request: VoiceGenerationRequest,
    ) -> VoiceGenerationResult:
        ...


class NarrationTooShortError(ValueError):
    """Raised when measured narration is below its requested minimum."""

    def __init__(self, message: str, result: VoiceGenerationResult) -> None:
        super().__init__(message)
        self.result = result


class VoiceEngine:
    """Create and manage narration audio for Ritzz scripts."""

    def __init__(
        self,
        provider: VoiceProvider,
        duration_probe=None,
    ) -> None:
        self.provider = provider
        self.duration_probe = duration_probe or probe_audio_duration

    def load_script(
        self,
        script_file: str | Path,
    ) -> Script:
        """Load a script from JSON."""

        path = Path(script_file)

        if not path.exists():
            raise FileNotFoundError(
                f"Script file not found: {path}"
            )

        return Script.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def create_request(
        self,
        script: Script,
        voice_id: str,
        output_directory: str | Path,
        output_filename: str = "narration.mp3",
        model_id: VoiceModel = "eleven_multilingual_v2",
        production_config: ProductionConfig | None = None,
    ) -> VoiceGenerationRequest:
        """Create a voice-generation request from a script."""

        text = self._build_narration(script)


        config = production_config or ProductionConfig(
            target_duration_seconds=script.target_duration_seconds,
            minimum_duration_seconds=script.target_duration_seconds,
        )
        return VoiceGenerationRequest(
            voice_id=voice_id,
            model_id=model_id,
            text=text,
            output_directory=str(output_directory),
            output_filename=output_filename,
            minimum_duration_seconds=float(config.minimum_duration_seconds),
        )

    def generate(
        self,
        request: VoiceGenerationRequest,
    ) -> VoiceGenerationResult:
        """Generate narration through the configured provider."""

        result = self.provider.generate(request)

        if result.status == "completed":
            self._validate_result(result)
            self._validate_measured_duration(result, request)

        return result

    def _validate_measured_duration(
        self,
        result: VoiceGenerationResult,
        request: VoiceGenerationRequest,
    ) -> None:
        minimum = request.minimum_duration_seconds
        if minimum is None:
            return

        audio_path = Path(result.file_path or "")
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise ValueError(
                "Generated narration audio is missing or empty; "
                "its minimum duration cannot be verified."
            )

        actual = float(self.duration_probe(audio_path))
        if not math.isfinite(actual) or actual <= 0:
            raise ValueError(
                "Measured narration duration must be positive and finite."
            )

        result.actual_duration_seconds = actual
        result.minimum_duration_seconds = minimum
        if actual >= minimum:
            return

        words = len(re.findall(r"\b[\w’'-]+\b", request.text))
        recommended_words = math.ceil(words * minimum / actual * 1.08)
        additional_words = max(1, recommended_words - words)
        message = (
            f"Generated narration measured {actual:.3f}s; the required minimum "
            f"is {minimum:.3f}s. Add approximately {additional_words} words to "
            "the script and regenerate. This audio cannot proceed to scene timing."
        )
        result.status = "failed"
        result.error_message = message
        raise NarrationTooShortError(message, result)

    def create_voice(
        self,
        script_file: str | Path,
        voice_id: str,
        output_directory: str | Path,
        output_filename: str = "narration.mp3",
        model_id: VoiceModel = "eleven_multilingual_v2",
        production_config: ProductionConfig | None = None,
    ) -> VoiceGenerationResult:
        """Load a script, create a request, and generate narration."""

        script = self.load_script(script_file)

        request = self.create_request(
            script=script,
            voice_id=voice_id,
            output_directory=output_directory,
            output_filename=output_filename,
            model_id=model_id,
            production_config=production_config,
        )

        return self.generate(request)

    @staticmethod
    def _build_narration(
        script: Script,
    ) -> str:
        """Combine all script section narration into one text."""

        parts: list[str] = []

        for section in script.sections:
            narration = ensure_terminal_punctuation(
                section.narration
            )

            if narration:
                parts.append(narration)

        if not parts:
            raise ValueError(
                "Script contains no narration."
            )

        return "\n\n".join(parts)

    @staticmethod
    def _validate_result(
        result: VoiceGenerationResult,
    ) -> None:
        """Validate a successful generation result."""

        if not result.file_path:
            raise ValueError(
                "Completed voice generation has no file path."
            )

        if result.duration_seconds is None:
            raise ValueError(
                "Completed voice generation has no duration."
            )

        if result.duration_seconds <= 0:
            raise ValueError(
                "Completed voice generation has invalid duration."
            )

    @staticmethod
    def save_result(
        result: VoiceGenerationResult,
        output_file: str | Path,
    ) -> None:
        """Save generation metadata as JSON."""

        path = Path(output_file)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def load_result(
        result_file: str | Path,
    ) -> VoiceGenerationResult:
        """Load generation metadata from JSON."""

        path = Path(result_file)

        if not path.exists():
            raise FileNotFoundError(
                f"Voice result file not found: {path}"
            )

        return VoiceGenerationResult.model_validate_json(
            path.read_text(encoding="utf-8")
        )
