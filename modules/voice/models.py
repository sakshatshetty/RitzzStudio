from typing import Literal

from pydantic import BaseModel, Field, field_validator

from modules.voice.text import ensure_terminal_punctuation


VoiceModel = Literal[
    "eleven_v3",
    "eleven_multilingual_v2",
    "eleven_flash_v2_5",
]


VoiceStatus = Literal[
    "pending",
    "generating",
    "completed",
    "failed",
]


class VoiceAlignment(BaseModel):
    """Character-level timing returned by a TTS provider."""

    characters: list[str] = Field(
        default_factory=list
    )

    character_start_times_seconds: list[float] = Field(
        default_factory=list
    )

    character_end_times_seconds: list[float] = Field(
        default_factory=list
    )


class VoiceSettings(BaseModel):
    """Consistent ElevenLabs delivery controls for narration generation."""

    stability: float = Field(default=0.72, ge=0, le=1)
    similarity_boost: float = Field(default=0.75, ge=0, le=1)
    style: float = Field(default=0, ge=0, le=1)
    use_speaker_boost: bool = True
    speed: float = Field(default=0.95, ge=0.7, le=1.2)


class VoiceGenerationRequest(BaseModel):
    """Request to generate narration audio."""

    voice_id: str

    model_id: VoiceModel = (
        "eleven_multilingual_v2"
    )

    text: str = Field(
        min_length=1
    )

    output_directory: str

    output_filename: str = (
        "narration.mp3"
    )

    output_format: str = (
        "mp3_44100_128"
    )

    voice_settings: VoiceSettings = Field(default_factory=VoiceSettings)

    minimum_duration_seconds: float | None = Field(
        default=None,
        gt=0,
    )

    @field_validator("text")
    @classmethod
    def prepare_text_for_speech(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Narration text cannot be blank.")
        return ensure_terminal_punctuation(value)


class VoiceAsset(BaseModel):
    """Generated voice/audio asset."""

    voice_id: str

    model_id: VoiceModel

    status: VoiceStatus

    file_path: str | None = None

    duration_seconds: float | None = Field(
        default=None,
        ge=0,
    )

    character_count: int = Field(
        default=0,
        ge=0,
    )


class VoiceGenerationResult(BaseModel):
    """Result returned after voice generation."""

    voice_id: str

    model_id: VoiceModel

    status: VoiceStatus

    file_path: str | None = None

    duration_seconds: float | None = None

    actual_duration_seconds: float | None = Field(default=None, ge=0)

    minimum_duration_seconds: float | None = Field(default=None, ge=0)

    character_count: int = 0

    alignment: VoiceAlignment | None = None

    error_message: str | None = None
