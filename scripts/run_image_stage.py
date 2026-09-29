"""Generate timed-scene images for the approved test project."""

import os
from pathlib import Path

from modules.image.batch import ImageBatchEngine
from modules.image.character_profile import load_character_profile
from modules.image.engine import ImageEngine
from modules.image.providers.openai import OpenAIImageProvider
from modules.image.prompt_builder import ImagePromptBuilder
from modules.project.manager import ProjectManager
from modules.storyboard.models import Storyboard


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
        ImageEngine(OpenAIImageProvider()),
        prompt_builder=ImagePromptBuilder(
            character_profile=load_character_profile(project_directory)
        ),
    )
    assets = engine.generate(storyboard, image_directory)
    engine.save_manifest(assets, manifest_file)
    failed = [asset for asset in assets if asset.status != "completed"]
    print(f"Generated images: {len(assets) - len(failed)}/{len(assets)}")
    print(f"Manifest: {manifest_file}")
    if failed:
        for asset in failed:
            print(f"{asset.scene_id}: {asset.error_message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
