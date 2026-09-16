from pathlib import Path
import json

from modules.image.engine import ImageEngine
from modules.image.models import (
    ImageAsset,
    ImageGenerationRequest,
)
from modules.image.prompt_builder import ImagePromptBuilder
from modules.storyboard.models import Storyboard


class ImageBatchEngine:
    """Create and generate image requests from a storyboard."""

    def __init__(
        self,
        image_engine: ImageEngine,
        prompt_builder: ImagePromptBuilder | None = None,
    ) -> None:
        self.image_engine = image_engine
        self.prompt_builder = (
            prompt_builder
            if prompt_builder is not None
            else ImagePromptBuilder()
        )

    def load_storyboard(
        self,
        storyboard_file: str | Path,
    ) -> Storyboard:
        """Load a storyboard JSON file."""

        path = Path(storyboard_file)

        if not path.exists():
            raise FileNotFoundError(
                f"Storyboard file not found: {path}"
            )

        return Storyboard.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def create_requests(
        self,
        storyboard: Storyboard,
        output_directory: str | Path,
    ) -> list[ImageGenerationRequest]:
        """Create one image-generation request for every storyboard scene."""

        requests: list[ImageGenerationRequest] = []

        for scene in storyboard.scenes:
            prompt = self.prompt_builder.build(scene)

            request = self.image_engine.create_request(
                image_id=scene.scene_id,
                scene_id=scene.scene_id,
                prompt=prompt,
                output_directory=output_directory,
            )

            requests.append(request)

        return requests

    def generate(
        self,
        storyboard: Storyboard,
        output_directory: str | Path,
    ) -> list[ImageAsset]:
        """Generate images for every storyboard scene."""

        if not storyboard.scenes:
            raise ValueError(
                "Cannot generate images from an empty storyboard."
            )

        requests = self.create_requests(
            storyboard=storyboard,
            output_directory=output_directory,
        )

        assets: list[ImageAsset] = []

        for request in requests:
            asset = self.image_engine.generate_asset(request)
            assets.append(asset)

        return assets

    @staticmethod
    def save_manifest(
        assets: list[ImageAsset],
        output_file: str | Path,
    ) -> None:
        """Save image assets as a JSON manifest."""

        path = Path(output_file)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = [
            asset.model_dump()
            for asset in assets
        ]

        path.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def load_manifest(
        manifest_file: str | Path,
    ) -> list[ImageAsset]:
        """Load an image manifest from JSON."""

        path = Path(manifest_file)

        if not path.exists():
            raise FileNotFoundError(
                f"Image manifest not found: {path}"
            )

        data = json.loads(
            path.read_text(encoding="utf-8")
        )

        return [
            ImageAsset.model_validate(item)
            for item in data
        ]