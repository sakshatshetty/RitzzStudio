from typing import Literal

from pydantic import BaseModel, Field


MotionType = Literal[
    "static",
    "slow_zoom_in",
    "slow_zoom_out",
    "pan_left",
    "pan_right",
    "pan_up",
    "pan_down",
]


class MotionInstruction(BaseModel):
    """
    Motion instructions for one video scene.

    Coordinates are normalized from 0.0 to 1.0.
    """

    scene_id: str

    start_seconds: float = Field(
        ge=0
    )

    duration_seconds: float = Field(
        gt=0
    )

    motion: MotionType = "static"

    zoom_start: float = Field(
        gt=0
    )

    zoom_end: float = Field(
        gt=0
    )

    position_x_start: float = Field(
        ge=0,
        le=1,
    )

    position_x_end: float = Field(
        ge=0,
        le=1,
    )

    position_y_start: float = Field(
        ge=0,
        le=1,
    )

    position_y_end: float = Field(
        ge=0,
        le=1,
    )


class VideoMotionPlan(BaseModel):
    """
    Complete motion plan for a video.
    """

    topic: str

    width: int = Field(
        gt=0
    )

    height: int = Field(
        gt=0
    )

    fps: int = Field(
        gt=0
    )

    instructions: list[MotionInstruction] = Field(
        default_factory=list
    )

    total_duration_seconds: float = Field(
        gt=0
    )


class VideoMotionRequest(BaseModel):
    """
    Request for creating a motion plan.
    """

    storyboard_file: str
    assembly_plan_file: str


class VideoMotionResult(BaseModel):
    """
    Result produced by the motion engine.
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