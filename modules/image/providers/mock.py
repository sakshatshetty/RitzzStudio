from pathlib import Path

from modules.image.models import (
    ImageGenerationRequest,
    ImageGenerationResult,
)


class MockImageProvider:
    """Test image provider that creates placeholder files."""

    def __init__(
        self,
        fail_scene_id: str | None = None,
    ) -> None:
        self.fail_scene_id = fail_scene_id
        self.calls: list[ImageGenerationRequest] = []

    def generate(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        self.calls.append(request)

        if request.scene_id == self.fail_scene_id:
            return ImageGenerationResult(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider=request.provider,
                status="failed",
                file_path=None,
                error_message="Mock generation failure.",
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
            b"RITZZ_MOCK_IMAGE"
        )

        return ImageGenerationResult(
            image_id=request.image_id,
            scene_id=request.scene_id,
            provider=request.provider,
            status="completed",
            file_path=str(output_path),
            error_message=None,
        )