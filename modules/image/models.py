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
    image_id: str
    scene_id: str
    provider: ImageProvider
    prompt: str = Field(min_length=1)
    file_path: str | None = None
    status: ImageStatus = "pending"
    error_message: str | None = None


class ImageGenerationRequest(BaseModel):
    image_id: str
    scene_id: str
    prompt: str = Field(min_length=1)
    provider: ImageProvider = "openai"
    output_directory: str

    # Ritzz production image format: exact 16:9.
    width: int = Field(default=1536, gt=0)
    height: int = Field(default=864, gt=0)


class ImageGenerationResult(BaseModel):
    image_id: str
    scene_id: str
    provider: ImageProvider
    status: ImageStatus
    file_path: str | None = None
    error_message: str | None = None