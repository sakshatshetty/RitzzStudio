from typing import Literal

from pydantic import BaseModel, Field


class NarrationAlignment(BaseModel):
    """
    Character-level timing information from ElevenLabs.
    """

    characters: list[str] = Field(
        min_length=1
    )

    character_start_times_seconds: list[float] = Field(
        min_length=1
    )

    character_end_times_seconds: list[float] = Field(
        min_length=1
    )

    audio_duration_seconds: float = Field(
        gt=0
    )


class VideoSynchronizationRequest(BaseModel):
    """
    Request for synchronizing a video assembly plan
    against actual narration timestamps.
    """

    storyboard_file: str
    assembly_plan_file: str
    narration_result_file: str


class VideoSynchronizationResult(BaseModel):
    """
    Result produced by the synchronization engine.
    """

    status: Literal[
        "completed",
        "failed",
    ]

    plan_file: str | None = None

    scene_count: int = Field(
        default=0,
        ge=0,
    )

    total_duration_seconds: float = Field(
        default=0,
        ge=0,
    )

    error_message: str | None = None