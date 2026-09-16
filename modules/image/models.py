from typing import Literal

from pydantic import BaseModel, Field


ImageStatus = Literal[
    "pending",
    "generating",
    "completed",
    "failed",
]


ImageProvider = Literal[
    "openai",
]


class ImageAsset(BaseModel):
    """A generated image associated with a storyboard scene."""

    image_id: str
    scene_id: str

    provider: ImageProvider

    prompt: str = Field(
        min_length=1,
    )

    file_path: str | None = None

    status: ImageStatus = "pending"

    error_message: str | None = None


class ImageGenerationRequest(BaseModel):
    """Request to generate an image for a storyboard scene."""

    image_id: str
    scene_id: str

    prompt: str = Field(
        min_length=1,
    )

    provider: ImageProvider = "openai"

    output_directory: str

    width: int = Field(
        default=1024,
        gt=0,
    )

    height: int = Field(
        default=1024,
        gt=0,
    )


class ImageGenerationResult(BaseModel):
    """Result returned after an image generation attempt."""

    image_id: str
    scene_id: str

    provider: ImageProvider

    status: ImageStatus

    file_path: str | None = None

    error_message: str | None = None