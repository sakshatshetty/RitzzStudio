"""Dedicated narration workflow for the dynamic three-minute pilot."""

import json
import math
from pathlib import Path
from typing import Protocol

from modules.storyboard.models import Storyboard
from modules.voice.audio import probe_audio_duration
from modules.voice.models import VoiceGenerationRequest, VoiceGenerationResult, VoiceModel


class PilotVoiceProvider(Protocol):
    def generate(self, request: VoiceGenerationRequest) -> VoiceGenerationResult: ...


class NarrationPreflightError(ValueError):
    """Raised when the script is too short to plausibly meet its duration target."""


class NarrationTooShortError(ValueError):
    """Raised when measured audio duration misses the required minimum."""


class PilotNarrationEngine:
    AUDIO_FILENAME = "narration_3min.mp3"
    RESULT_FILENAME = "narration_3min_timestamps.json"
    HISTORY_FILENAME = "narration_duration_history.json"
    DEFAULT_WPM = 176.8
    DURATION_BUFFER = 1.08
    MAX_HISTORY_SAMPLES = 20

    def __init__(self, provider: PilotVoiceProvider, duration_probe=None) -> None:
        self.provider = provider
        self.duration_probe = duration_probe or self.probe_audio_duration

    @staticmethod
    def load_storyboard(path: str | Path) -> Storyboard:
        storyboard_path = Path(path)
        if not storyboard_path.is_file():
            raise FileNotFoundError(f"Pilot storyboard not found: {storyboard_path}")
        return Storyboard.model_validate_json(storyboard_path.read_text(encoding="utf-8"))

    @staticmethod
    def narration_text(storyboard: Storyboard) -> str:
        parts = [scene.narration.strip() for scene in storyboard.scenes]
        if not parts or any(not part for part in parts):
            raise ValueError("Every pilot scene must contain narration.")
        return "\n\n".join(parts)

    @staticmethod
    def count_words(text: str) -> int:
        return len(text.split())

    @staticmethod
    def probe_audio_duration(audio_path: str | Path) -> float:
        return probe_audio_duration(audio_path)

    @staticmethod
    def _load_history(path: Path) -> list[dict]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    @classmethod
    def _estimated_wpm(cls, history: list[dict], voice_id: str, model_id: str) -> float:
        samples = [sample for sample in history[-cls.MAX_HISTORY_SAMPLES:]
                   if isinstance(sample, dict) and sample.get("voice_id") == voice_id
                   and sample.get("model_id") == model_id]
        totals = []
        for sample in samples:
            try:
                words, seconds = int(sample["word_count"]), float(sample["actual_duration_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            if words > 0 and seconds > 0 and math.isfinite(seconds):
                totals.append((words, seconds))
        if not totals:
            return cls.DEFAULT_WPM
        return sum(words for words, _ in totals) * 60 / sum(seconds for _, seconds in totals)

    def generate(self, storyboard_file: str | Path, output_directory: str | Path,
                 voice_id: str, model_id: VoiceModel = "eleven_multilingual_v2",
                 minimum_duration_seconds: float | None = 180.0) -> VoiceGenerationResult:
        if minimum_duration_seconds is not None and (
            not math.isfinite(minimum_duration_seconds) or minimum_duration_seconds <= 0
        ):
            raise ValueError("minimum_duration_seconds must be positive and finite.")
        storyboard = self.load_storyboard(storyboard_file)
        text = self.narration_text(storyboard)
        word_count = self.count_words(text)
        output_dir = Path(output_directory).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        history_path = output_dir / self.HISTORY_FILENAME
        history = self._load_history(history_path)
        wpm = self._estimated_wpm(history, voice_id, model_id)
        minimum_words = (math.ceil(minimum_duration_seconds * wpm / 60 * self.DURATION_BUFFER)
                         if minimum_duration_seconds is not None else None)
        if minimum_words is not None and word_count < minimum_words:
            raise NarrationPreflightError(
                f"Pilot script has {word_count} words; estimated minimum is {minimum_words} "
                f"for {minimum_duration_seconds:.1f}s at {wpm:.1f} WPM with an 8% buffer. "
                f"Add about {minimum_words - word_count} words before generating audio."
            )

        request = VoiceGenerationRequest(
            voice_id=voice_id, model_id=model_id, text=text,
            output_directory=str(output_dir), output_filename=self.AUDIO_FILENAME,
        )
        result = self.provider.generate(request)
        if result.status != "completed":
            raise RuntimeError(f"Pilot narration generation failed: {result.error_message or 'unknown error'}")
        if not result.file_path or not result.duration_seconds or result.duration_seconds <= 0:
            raise ValueError("Completed pilot narration is missing its audio path or duration.")
        if result.alignment is None or not result.alignment.characters:
            raise ValueError("Pilot narration did not return character timestamps.")
        audio_path = Path(result.file_path).resolve()
        if audio_path.parent != output_dir or audio_path.name != self.AUDIO_FILENAME:
            raise ValueError("Pilot narration provider returned a path outside the dedicated pilot output.")
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise ValueError("Generated pilot audio is missing or empty.")

        actual_duration = float(self.duration_probe(audio_path))
        if not math.isfinite(actual_duration) or actual_duration <= 0:
            raise ValueError("Measured pilot audio duration must be positive and finite.")
        result.actual_duration_seconds = actual_duration
        result.minimum_duration_seconds = minimum_duration_seconds
        from modules.voice.engine import VoiceEngine
        VoiceEngine.save_result(result, output_dir / self.RESULT_FILENAME)

        history.append({"voice_id": voice_id, "model_id": model_id, "word_count": word_count,
                        "actual_duration_seconds": actual_duration})
        history_path.write_text(json.dumps(history[-self.MAX_HISTORY_SAMPLES:], indent=2), encoding="utf-8")
        if minimum_duration_seconds is not None and actual_duration < minimum_duration_seconds:
            observed_wpm = word_count * 60 / actual_duration
            needed_words = math.ceil(minimum_duration_seconds * observed_wpm / 60 * self.DURATION_BUFFER)
            raise NarrationTooShortError(
                f"Generated narration is {actual_duration:.3f}s; minimum is "
                f"{minimum_duration_seconds:.3f}s (short by "
                f"{minimum_duration_seconds - actual_duration:.3f}s). Add approximately "
                f"{max(0, needed_words - word_count)} words and regenerate."
            )
        return result
