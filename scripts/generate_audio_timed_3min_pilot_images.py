import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.image.batch import ImageBatchEngine
from modules.image.engine import ImageEngine
from modules.image.providers.openai import OpenAIImageProvider
from modules.storyboard.models import Storyboard

PILOT_DIRECTORY = PROJECT_ROOT / "projects" / "20260820_001_why_do_pirates_wear_eye_patches" / "pilot_3min"
STORYBOARD_FILE = PILOT_DIRECTORY / "storyboard_audio_timed.json"
IMAGE_DIRECTORY = PILOT_DIRECTORY / "images_audio_timed"
MANIFEST_FILE = IMAGE_DIRECTORY / "image_manifest.json"


def main() -> int:
    storyboard = Storyboard.model_validate_json(STORYBOARD_FILE.read_text(encoding="utf-8"))
    if not storyboard.scenes:
        raise ValueError("Audio-timed storyboard has no scenes.")
    if any(scene.duration_seconds <= 0 for scene in storyboard.scenes):
        raise ValueError("Audio-timed storyboard contains an invalid scene duration.")
    engine = ImageBatchEngine(ImageEngine(OpenAIImageProvider()))
    assets = engine.generate(storyboard, IMAGE_DIRECTORY)
    engine.save_manifest(assets, MANIFEST_FILE)
    failed = [asset for asset in assets if asset.status != "completed"]
    print(f"Generated images: {len(assets) - len(failed)}/{len(storyboard.scenes)}")
    print(f"Manifest: {MANIFEST_FILE}")
    if failed:
        for asset in failed:
            print(f"{asset.scene_id}: {asset.error_message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
