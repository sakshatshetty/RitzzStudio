from typing import Literal

from pydantic import BaseModel, Field


class VideoRenderRequest(BaseModel):
    """
    Request for rendering a synchronized video.
    """

    assembly_plan_file: str
    motion_plan_file: str
    output_file: str
    audio_file: str | None = None


class VideoRenderResult(BaseModel):
    """
    Result produced by the FFmpeg video renderer.
    """

    status: Literal[
        "completed",
        "failed",
    ]

    output_file: str | None = None

    duration_seconds: float = Field(
        default=0,
        ge=0,
    )

    width: int = Field(
        default=0,
        ge=0,
    )

    height: int = Field(
        default=0,
        ge=0,
    )

    fps: float = Field(
        default=0,
        ge=0,
    )

    file_size_bytes: int = Field(
        default=0,
        ge=0,
    )

    error_message: str | None = None