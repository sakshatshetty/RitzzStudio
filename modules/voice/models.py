from typing import Literal

from pydantic import BaseModel, Field


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

    character_count: int = 0

    alignment: VoiceAlignment | None = None

    error_message: str | None = None