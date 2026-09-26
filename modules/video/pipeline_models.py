from typing import Literal

from pydantic import BaseModel, Field


PipelineStageName = Literal[
    "asset_validation",
    "assembly",
    "synchronization",
    "motion",
    "render",
]


class VideoProductionRequest(BaseModel):
    """
    Request for running the complete Ritzz video
    production workflow.
    """

    storyboard_file: str
    image_directory: str
    narration_result_file: str
    audio_file: str | None = None
    output_directory: str
    output_video_file: str | None = None
    resume: bool = True
    retry_from_stage: PipelineStageName | None = None
    enable_image_ai_qa: bool = False


class VideoProductionResult(BaseModel):
    """
    Result produced by the complete video
    production pipeline.
    """

    status: Literal[
        "completed",
        "failed",
    ]

    video_plan_file: str | None = None
    synchronized_plan_file: str | None = None
    motion_plan_file: str | None = None
    output_video_file: str | None = None

    scene_count: int = Field(
        default=0,
        ge=0,
    )

    duration_seconds: float = Field(
        default=0,
        ge=0,
    )

    error_message: str | None = None
    technical_qa_status: Literal["PASS", "REVIEW", "FAIL"] | None = None
    image_ai_qa_status: Literal["PASS", "REVIEW", "FAIL"] | None = None
    approval_status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"