"""Generate timed-scene images for the approved test project."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.image.batch import ImageBatchEngine
from modules.image.character_profile import load_character_profile
from modules.image.engine import ImageEngine
from modules.image.models import IMAGE_MODEL_OPTIONS
from modules.image.prompt_builder import ImagePromptBuilder
from modules.image.providers.openai import OpenAIImageProvider
from modules.image.providers.replicate import ReplicateFluxSchnellProvider
from modules.project.manager import ProjectManager
from modules.storyboard.models import Storyboard
from modules.storyboard.visual_context import load_visual_world_bible


def _create_image_engine(model: str | None = None) -> ImageEngine:
    selected_model = model or os.environ.get(
        "RITZZ_IMAGE_MODEL",
        "FLUX_SCHNELL",
    )
    if selected_model == "FLUX_SCHNELL":
        return ImageEngine(
            ReplicateFluxSchnellProvider(),
            provider_name="replicate",
        )
    if selected_model == "GPT_IMAGE_2":
        return ImageEngine(
            OpenAIImageProvider(),
            provider_name="openai",
        )
    supported = ", ".join(IMAGE_MODEL_OPTIONS)
    raise ValueError(
        f"Unsupported RITZZ_IMAGE_MODEL {selected_model!r}; choose one of: {supported}."
    )


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    project_manager = ProjectManager(Path("projects"))
    project = project_manager.load_project(project_id)
    project_directory = project_manager.get_project_path(project)
    storyboard_file = project_directory / "storyboard" / "storyboard_audio_timed.json"
    image_directory = project_directory / "images"
    manifest_file = image_directory / "image_manifest.json"
    storyboard = Storyboard.model_validate_json(
        storyboard_file.read_text(encoding="utf-8")
    )
    if not storyboard.scenes:
        raise ValueError("Audio-timed storyboard has no scenes.")

    engine = ImageBatchEngine(
        _create_image_engine(),
        prompt_builder=ImagePromptBuilder(
            character_profile=load_character_profile(project_directory),
            visual_world=load_visual_world_bible(project_directory),
        ),
    )
    assets = engine.generate(
        storyboard,
        image_directory,
        manifest_file=manifest_file,
        force_regenerate=os.environ.get("RITZZ_FORCE_REGENERATE_IMAGES") == "true",
    )
    failed = [asset for asset in assets if asset.status != "completed"]
    print(f"Ready images (new or resumed): {len(assets) - len(failed)}/{len(assets)}")
    print(f"Manifest: {manifest_file}")
    if failed:
        for asset in failed:
            print(f"{asset.scene_id}: {asset.error_message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
