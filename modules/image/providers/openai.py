import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from modules.image.models import (
    ImageGenerationRequest,
    ImageGenerationResult,
)


load_dotenv()


class OpenAIImageProvider:
    """
    OpenAI image-generation provider for Ritzz.
    """

    MODEL = "gpt-image-2"
    QUALITY = "medium"

    def __init__(
        self,
        api_key: str | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("OPENAI_API_KEY")
        )

        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured."
            )

        self.client = OpenAI(
            api_key=self.api_key
        )

    def generate(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        try:
            size = (
                f"{request.width}x{request.height}"
            )

            response = self.client.images.generate(
                model=self.MODEL,
                prompt=request.prompt,
                size=size,
                quality=self.QUALITY,
                n=1,
            )

            if not response.data:
                raise ValueError(
                    "OpenAI returned no image data."
                )

            image_data = response.data[0].b64_json

            if not image_data:
                raise ValueError(
                    "OpenAI response did not contain "
                    "base64 image data."
                )

            try:
                image_bytes = base64.b64decode(
                    image_data,
                    validate=True,
                )
            except Exception as exc:
                raise ValueError(
                    "OpenAI returned invalid Base64 "
                    "image data."
                ) from exc

            if not image_bytes:
                raise ValueError(
                    "OpenAI returned empty image data."
                )

            output_directory = Path(
                request.output_directory
            )

            output_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            output_path = (
                output_directory
                / f"{request.image_id}.png"
            )

            output_path.write_bytes(
                image_bytes
            )

            return ImageGenerationResult(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider=request.provider,
                status="completed",
                file_path=str(output_path),
                error_message=None,
            )

        except Exception as exc:
            return ImageGenerationResult(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider=request.provider,
                status="failed",
                file_path=None,
                error_message=str(exc),
            )