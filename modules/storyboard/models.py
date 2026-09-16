from typing import Literal

from pydantic import BaseModel, Field


VisualStyle = Literal[
    "stickman",
    "illustration",
    "diagram",
    "map",
    "text",
    "photo_reference",
]


CameraMotion = Literal[
    "static",
    "slow_zoom_in",
    "slow_zoom_out",
    "pan_left",
    "pan_right",
    "pan_up",
    "pan_down",
]


TransitionType = Literal[
    "cut",
    "fade",
]


class StoryboardScene(BaseModel):
    """A single visual scene in a Ritzz video."""

    scene_id: str
    section_id: str

    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(
        gt=0,
        le=30,
    )

    narration: str

    visual_style: VisualStyle = "stickman"

    visual_description: str = Field(
        min_length=10,
    )

    character_action: str = ""

    background: str = ""

    props: list[str] = Field(
        default_factory=list
    )

    text_overlay: str = ""

    camera_motion: CameraMotion = "static"

    transition: TransitionType = "cut"

    research_sources: list[str] = Field(
        default_factory=list
    )

    image_prompt: str = Field(
        min_length=10,
    )


class Storyboard(BaseModel):
    """Complete visual storyboard for a Ritzz video."""

    topic: str

    target_duration_seconds: int

    scenes: list[StoryboardScene] = Field(
        default_factory=list
    )

    total_scene_duration_seconds: float

    target_scene_duration_seconds: float = 5.0