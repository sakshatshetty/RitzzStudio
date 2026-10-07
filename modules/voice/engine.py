import math
import re
from itertools import pairwise
from pathlib import Path
from typing import Protocol

from modules.project.config import ProductionConfig
from modules.script.models import Script
from modules.voice.audio import probe_audio_duration
from modules.voice.models import (
    VoiceGenerationRequest,
    VoiceGenerationResult,
    VoiceModel,
)
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


class VoiceAlignmentError(RuntimeError):
    """Raised when completed audio has incomplete or invalid alignment."""


class OpeningHookValidationError(ValueError):
    """Raised when the generated opening fails its spoken-hook requirement."""


class VoiceEngine:
    """Create and manage narration audio for Ritzz scripts."""

    OPENING_HOOK_MINIMUM_SECONDS = 20.0
    OPENING_HOOK_MAXIMUM_SECONDS = 35.0

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
            preserve_text=script.user_supplied,
            text=text,
            output_directory=str(output_directory),
            output_filename=output_filename,
            opening_hook=(
                script.hook
                if script.script_profile and script.hook.strip()
                else None
            ),
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
        hook_error = None
        if request.opening_hook is not None:
            (
                result.opening_hook_duration_seconds,
                hook_error,
            ) = self._measure_opening_hook(request, result)

        minimum = request.minimum_duration_seconds
        if minimum is None:
            if request.opening_hook is not None:
                self._record_project_voice_qa(
                    request,
                    result,
                    True,
                    hook_error,
                )
                if hook_error:
                    result.status = "failed"
                    result.error_message = hook_error
                    raise OpeningHookValidationError(hook_error)
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
        alignment_valid = self._record_project_voice_qa(
            request,
            result,
            actual >= minimum,
            hook_error,
        )
        if hook_error:
            result.status = "failed"
            result.error_message = hook_error
            raise OpeningHookValidationError(hook_error)
        if actual >= minimum:
            if not alignment_valid:
                result.status = "failed"
                result.error_message = (
                    "Generated narration has missing or invalid character alignment."
                )
                raise VoiceAlignmentError(result.error_message)
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

    @classmethod
    def _measure_opening_hook(
        cls,
        request: VoiceGenerationRequest,
        result: VoiceGenerationResult,
    ) -> tuple[float | None, str | None]:
        hook = (request.opening_hook or "").strip()
        leading_whitespace = len(request.text) - len(request.text.lstrip())
        spoken_text = request.text[leading_whitespace:]
        if not hook or not spoken_text.casefold().startswith(hook.casefold()):
            return None, (
                "The opening hook is not the first spoken narration text; "
                "regenerate the script before continuing."
            )

        alignment = result.alignment
        if alignment is None:
            return None, "The opening hook has no character-level audio alignment."
        if not (
            len(alignment.characters)
            == len(alignment.character_start_times_seconds)
            == len(alignment.character_end_times_seconds)
        ):
            return None, "The opening hook alignment is incomplete."

        first_character = leading_whitespace
        after_hook = first_character + len(hook)
        if len(alignment.characters) < after_hook:
            return None, "The audio alignment ends before the opening hook."
        aligned_hook = "".join(alignment.characters[first_character:after_hook])
        if aligned_hook.casefold() != hook.casefold():
            return None, (
                "The generated audio alignment does not match the opening hook text."
            )

        starts = alignment.character_start_times_seconds[first_character:after_hook]
        ends = alignment.character_end_times_seconds[first_character:after_hook]
        timestamps_valid = (
            bool(starts)
            and all(
                math.isfinite(start)
                and math.isfinite(end)
                and 0 <= start <= end
                for start, end in zip(starts, ends, strict=True)
            )
            and all(
                current >= previous
                for previous, current in pairwise(starts)
            )
            and all(
                current >= previous
                for previous, current in pairwise(ends)
            )
        )
        if not timestamps_valid:
            return None, "The opening hook has invalid character timestamps."

        duration = ends[-1] - starts[0]
        if not (
            cls.OPENING_HOOK_MINIMUM_SECONDS
            <= duration
            <= cls.OPENING_HOOK_MAXIMUM_SECONDS
        ):
            duration_requirement = (
                f"between {cls.OPENING_HOOK_MINIMUM_SECONDS:.1f}s and "
                f"{cls.OPENING_HOOK_MAXIMUM_SECONDS:.1f}s"
            )
            return duration, (
                f"The spoken curiosity hook lasts {duration:.3f}s; it must remain "
                f"{duration_requirement} in the actual narration."
            )
        return duration, None

    @staticmethod
    def _record_project_voice_qa(
        request: VoiceGenerationRequest,
        result: VoiceGenerationResult,
        duration_passed: bool,
        opening_hook_error: str | None = None,
    ) -> bool:
        project_directory = Path(request.output_directory).parent
        if not (project_directory / "project.json").is_file():
            return True

        from modules.qa.engine import record_stage_qa
        from modules.qa.models import QAStageResult

        alignment = result.alignment
        alignment_starts = (
            alignment.character_start_times_seconds if alignment is not None else []
        )
        alignment_ends = (
            alignment.character_end_times_seconds if alignment is not None else []
        )
        alignment_complete = bool(
            alignment
            and alignment.characters
            and len(alignment.characters)
            == len(alignment_starts)
            == len(alignment_ends)
        )
        timestamps_valid = bool(
            alignment_complete
            and all(
                math.isfinite(start)
                and math.isfinite(end)
                and 0 <= start <= end
                for start, end in zip(alignment_starts, alignment_ends)
            )
            and all(
                current >= previous
                for previous, current in pairwise(alignment_starts)
            )
        )
        findings = []
        recommendations = []
        if not alignment_complete or not timestamps_valid:
            findings.append("Character-level voice alignment is missing or invalid.")
            recommendations.append("Retry narration generation before scene timing.")
        if not duration_passed:
            findings.append(
                f"Narration is {result.actual_duration_seconds:.3f}s; minimum is {request.minimum_duration_seconds:.3f}s."
            )
            recommendations.append("Expand the script and regenerate narration; do not stretch the audio.")
        opening_hook_passed = (
            request.opening_hook is None or opening_hook_error is None
        )
        if opening_hook_error:
            findings.append(opening_hook_error)
            recommendations.append(
                "Revise only the opening hook to last between 20 and 35 seconds "
                "in actual narration, then regenerate narration."
            )
        status = (
            "PASS"
            if duration_passed and timestamps_valid and opening_hook_passed
            else "FAIL"
        )
        record_stage_qa(
            project_directory,
            QAStageResult(
                stage="voice",
                status=status,
                checks={
                    "minimum_duration": "PASS" if duration_passed else "FAIL",
                    "character_alignment": "PASS" if alignment_complete else "FAIL",
                    "timestamp_order": "PASS" if timestamps_valid else "FAIL",
                    "opening_hook_20_to_35_seconds": (
                        "PASS" if opening_hook_passed else "FAIL"
                    ),
                },
                findings=findings,
                recommendations=recommendations,
                metrics={
                    "opening_hook_duration_seconds": (
                        result.opening_hook_duration_seconds
                    ),
                },
            ),
        )
        return timestamps_valid

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

        def regenerate_request(
            feedback: str,
            *,
            hook_only: bool = False,
        ) -> VoiceGenerationRequest:
            project_directory = Path(script_file).parent.parent
            research_file = project_directory / "research" / "research.json"
            outline_file = project_directory / "outline" / "outline.json"
            if not research_file.is_file() or not outline_file.is_file():
                raise RuntimeError(
                    "Cannot revise narration without the saved research and outline."
                )
            from modules.script.engine import ScriptEngine

            script_engine = ScriptEngine()
            if hook_only:
                corrected_script = script_engine.repair_opening_hook(
                    script_file=script_file,
                    research_file=research_file,
                    feedback=feedback,
                    production_config=production_config,
                )
            else:
                corrected_script = script_engine.create_script(
                    research_file=research_file,
                    outline_file=outline_file,
                    script_directory=Path(script_file).parent,
                    force_refresh=True,
                    production_config=production_config,
                    qa_feedback=feedback,
                )
            return self.create_request(
                script=corrected_script,
                voice_id=voice_id,
                output_directory=output_directory,
                output_filename=output_filename,
                model_id=model_id,
                production_config=production_config,
            )

        try:
            return self.generate(request)
        except NarrationTooShortError as exc:
            if script.user_supplied:
                raise
            return self.generate(regenerate_request(str(exc)))
        except OpeningHookValidationError as exc:
            feedback = (
                f"{exc} Repair only the opening hook so its character-aligned "
                "duration is 20–35 seconds. Preserve its research support, early "
                "curiosity question, open loop, and continuity with the first "
                "investigation; do not resolve the central mystery."
            )
            return self.generate(regenerate_request(feedback, hook_only=True))
        except VoiceAlignmentError:
            return self.generate(request)

    @staticmethod
    def _build_narration(
        script: Script,
    ) -> str:
        """Combine all script section narration into one text."""

        parts: list[str] = []

        for section in script.sections:
            narration = (
                section.narration
                if script.user_supplied
                else ensure_terminal_punctuation(section.narration)
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
