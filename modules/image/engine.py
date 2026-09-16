from pathlib import Path
from typing import Protocol

from modules.image.models import (
    ImageAsset,
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageProvider,
)


class ImageProviderProtocol(Protocol):
    """Interface implemented by image-generation providers."""

    def generate(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        ...


class ImageEngine:
    """Orchestrates image generation through a provider."""

    def __init__(
        self,
        provider: ImageProviderProtocol,
    ) -> None:
        self.provider = provider

    def create_request(
        self,
        image_id: str,
        scene_id: str,
        prompt: str,
        output_directory: str | Path,
        provider: ImageProvider = "openai",
    ) -> ImageGenerationRequest:
        """Create an image-generation request."""

        return ImageGenerationRequest(
            image_id=image_id,
            scene_id=scene_id,
            prompt=prompt,
            provider=provider,
            output_directory=str(output_directory),
        )

    def generate(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        """Generate an image using the configured provider."""

        return self.provider.generate(request)

    def generate_asset(
        self,
        request: ImageGenerationRequest,
    ) -> ImageAsset:
        """Generate an image and convert the result to an ImageAsset."""

        result = self.generate(request)

        if result.status == "completed":
            if not result.file_path:
                raise ValueError(
                    "Completed image generation has no file path."
                )

            return ImageAsset(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider=request.provider,
                prompt=request.prompt,
                file_path=result.file_path,
                status="completed",
                error_message=None,
            )

        return ImageAsset(
            image_id=request.image_id,
            scene_id=request.scene_id,
            provider=request.provider,
            prompt=request.prompt,
            file_path=None,
            status="failed",
            error_message=result.error_message,
        )

    @staticmethod
    def save_asset(
        asset: ImageAsset,
        output_file: str | Path,
    ) -> None:
        """Save an ImageAsset as JSON."""

        path = Path(output_file)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            asset.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def load_asset(
        asset_file: str | Path,
    ) -> ImageAsset:
        """Load an ImageAsset from JSON."""

        path = Path(asset_file)

        if not path.exists():
            raise FileNotFoundError(
                f"Image asset file not found: {path}"
            )

        return ImageAsset.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    @staticmethod
    def build_output_filename(
        image_id: str,
    ) -> str:
        """Build a predictable PNG filename."""

        return f"{image_id}.png"