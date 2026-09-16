from pathlib import Path
from typing import Protocol

from modules.script.models import Script
from modules.voice.models import (
    VoiceGenerationRequest,
    VoiceGenerationResult,
    VoiceModel,
)


class VoiceProvider(Protocol):
    """Interface implemented by a real or mock voice provider."""

    def generate(
        self,
        request: VoiceGenerationRequest,
    ) -> VoiceGenerationResult:
        ...


class VoiceEngine:
    """Create and manage narration audio for Ritzz scripts."""

    def __init__(
        self,
        provider: VoiceProvider,
    ) -> None:
        self.provider = provider

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
    ) -> VoiceGenerationRequest:
        """Create a voice-generation request from a script."""

        text = self._build_narration(script)


        return VoiceGenerationRequest(
            voice_id=voice_id,
            model_id=model_id,
            text=text,
            output_directory=str(output_directory),
            output_filename=output_filename,
        )

    def generate(
        self,
        request: VoiceGenerationRequest,
    ) -> VoiceGenerationResult:
        """Generate narration through the configured provider."""

        result = self.provider.generate(request)

        if result.status == "completed":
            self._validate_result(result)

        return result

    def create_voice(
        self,
        script_file: str | Path,
        voice_id: str,
        output_directory: str | Path,
        output_filename: str = "narration.mp3",
        model_id: VoiceModel = "eleven_multilingual_v2",
    ) -> VoiceGenerationResult:
        """Load a script, create a request, and generate narration."""

        script = self.load_script(script_file)

        request = self.create_request(
            script=script,
            voice_id=voice_id,
            output_directory=output_directory,
            output_filename=output_filename,
            model_id=model_id,
        )

        return self.generate(request)

    @staticmethod
    def _build_narration(
        script: Script,
    ) -> str:
        """Combine all script section narration into one text."""

        parts: list[str] = []

        for section in script.sections:
            narration = section.narration.strip()

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