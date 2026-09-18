from typing import Literal

from pydantic import BaseModel, Field


VideoClipStatus = Literal[
    "ready",
    "missing",
    "invalid",
]


class VideoClip(BaseModel):
    """
    Represents one storyboard scene on the video timeline.
    """

    scene_id: str
    image_path: str
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    status: VideoClipStatus = "ready"


class VideoAssemblyPlan(BaseModel):
    """
    Complete static video assembly plan.

    Effects, synchronization, transitions and final
    rendering are implemented in later milestones.
    """

    topic: str
    width: int = Field(
        default=1536,
        gt=0,
    )
    height: int = Field(
        default=864,
        gt=0,
    )
    fps: int = Field(
        default=30,
        gt=0,
    )
    clips: list[VideoClip] = Field(
        default_factory=list
    )
    total_duration_seconds: float = Field(
        gt=0
    )
    audio_path: str | None = None


class VideoAssemblyRequest(BaseModel):
    """
    Request for building a video assembly plan.
    """

    storyboard_file: str
    image_directory: str
    audio_file: str | None = None

    width: int = Field(
        default=1536,
        gt=0,
    )
    height: int = Field(
        default=864,
        gt=0,
    )
    fps: int = Field(
        default=30,
        gt=0,
    )


class VideoAssemblyResult(BaseModel):
    """
    Result produced by the video assembly engine.
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