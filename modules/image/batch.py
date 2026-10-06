import json
import tempfile
from pathlib import Path

from modules.image.engine import ImageEngine
from modules.image.models import (
    ImageAsset,
    ImageGenerationRequest,
)
from modules.image.prompt_builder import ImagePromptBuilder
from modules.storyboard.models import Storyboard
from modules.video.image_asset_qa import inspect_image_asset


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
        manifest_file: str | Path | None = None,
    ) -> list[ImageAsset]:
        """Generate images, reusing valid matching assets from an optional manifest."""

        if not storyboard.scenes:
            raise ValueError(
                "Cannot generate images from an empty storyboard."
            )

        requests = self.create_requests(
            storyboard=storyboard,
            output_directory=output_directory,
        )

        existing_assets: dict[str, ImageAsset] = {}
        if manifest_file is not None and Path(manifest_file).is_file():
            existing_assets = {
                asset.scene_id: asset
                for asset in self.load_manifest(manifest_file)
            }

        assets: list[ImageAsset] = []
        for request in requests:
            expected_path = Path(request.output_directory) / f"{request.image_id}.png"
            previous_asset = existing_assets.get(request.scene_id)
            if previous_asset is not None and self._can_reuse_asset(
                previous_asset,
                request,
                expected_path,
            ):
                asset = previous_asset.model_copy(
                    update={"file_path": str(expected_path)}
                )
                assets.append(asset)
                if manifest_file is not None:
                    self.save_manifest(assets, manifest_file)
                continue

            assets.append(
                ImageAsset(
                    image_id=request.image_id,
                    scene_id=request.scene_id,
                    provider=request.provider,
                    prompt=request.prompt,
                    status="generating",
                )
            )
            if manifest_file is not None:
                self.save_manifest(assets, manifest_file)

            asset = self.image_engine.generate_asset(request)
            assets[-1] = asset
            if manifest_file is not None:
                self.save_manifest(assets, manifest_file)

        return assets

    @staticmethod
    def _can_reuse_asset(
        asset: ImageAsset,
        request: ImageGenerationRequest,
        expected_path: Path,
    ) -> bool:
        if (
            asset.status != "completed"
            or asset.image_id != request.image_id
            or asset.scene_id != request.scene_id
            or asset.provider != request.provider
            or asset.prompt != request.prompt
            or asset.file_path is None
            or not expected_path.is_file()
        ):
            return False
        try:
            inspection = inspect_image_asset(expected_path)
        except (OSError, ValueError):
            return False
        return (
            inspection.width == request.width
            and inspection.height == request.height
        )

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

        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as temporary:
            json.dump(data, temporary, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)

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