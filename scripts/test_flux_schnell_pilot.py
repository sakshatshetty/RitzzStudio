"""Generate four isolated FLUX Schnell samples with concise, explicit prompts."""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from modules.image.engine import ImageEngine
from modules.image.models import ImageAsset, ImageGenerationRequest
from modules.image.providers.replicate import ReplicateFluxSchnellProvider
from modules.storyboard.models import Storyboard, StoryboardScene


load_dotenv(PROJECT_ROOT / ".env")

PILOT_DIRECTORY = (
    PROJECT_ROOT / "projects" / "20260820_001_why_do_pirates_wear_eye_patches"
    / "pilot_3min"
)
STORYBOARD_FILE = PILOT_DIRECTORY / "storyboard_audio_timed.json"
TRIAL_DIRECTORY = PILOT_DIRECTORY / "images_audio_timed" / "flux_schnell_prompt_test"
TRIAL_SCENE_IDS = ("scene_001", "scene_004", "scene_002", "scene_005")

PIRATE_CHARACTER = (
    "The same simple full-body stick-figure pirate: round light-tan face, "
    "small dot eyes, friendly face, thin black line arms and legs, dark navy "
    "tricorne hat, red bandana, deep blue vest, and a black eye patch. "
    "Clearly a stick figure, never a skull or skeleton."
)
COMMON_STYLE = (
    "Wide 16:9 frame. Hand-drawn 2D explainer cartoon, thick clean black "
    "outlines, flat solid fills, simple shapes, uncluttered composition. "
    "Use a visibly colorful palette: turquoise ocean, pale blue sky, warm "
    "brown wood, red fabric, and gold accents. Keep the character and the "
    "entire scene in color."
)
NO_TEXT = "Do not include any words, letters, captions, labels, or signs."
EDITORIAL_TEXT_RULE = (
    "Include exactly one piece of lettering, the uppercase word \"{word}\", "
    "handwritten in plain black marker in the open cream sky at upper right. "
    "Black applies only to these letters. Keep every other part of the image colorful. "
    "No other writing, words, letters, captions, labels, or signs."
)


def build_trial_prompt(scene: StoryboardScene) -> str:
    scene_directions = {
        "scene_001": (
            f"Show {PIRATE_CHARACTER} standing on the deck of a small wooden "
            "sailing ship. He smiles and points to his eye patch. A red flag "
            "flies behind him over the bright turquoise sea. " + NO_TEXT
        ),
        "scene_004": (
            f"Show {PIRATE_CHARACTER} beside a colorful framed portrait of a "
            "pirate wearing an eye patch. He studies the portrait with a curious "
            "expression while holding an old blank parchment. Ship deck, blue sea, "
            "red flag, warm brown wood. " + NO_TEXT
        ),
        "scene_002": (
            f"Show {PIRATE_CHARACTER} on a ship deck, with his eye patch clearly "
            "visible and a friendly grin. Include a small wooden hook as a secondary "
            "prop, but keep the face and stick-figure body clear. "
            + EDITORIAL_TEXT_RULE.format(word="ICONIC")
        ),
        "scene_005": (
            f"Show {PIRATE_CHARACTER} in a small maritime museum, beside a framed "
            "colorful pirate portrait. A friendly stick-figure historian examines "
            "the portrait with a magnifying glass. Use blue-green walls, warm wood, "
            "and gold accents. "
            + EDITORIAL_TEXT_RULE.format(word="ACCURACY")
        ),
    }
    try:
        prompt = scene_directions[scene.scene_id]
    except KeyError as exc:
        raise ValueError(f"No FLUX trial prompt defined for {scene.scene_id}.") from exc

    if scene.text_overlay.strip():
        expected = EDITORIAL_TEXT_RULE.format(word=scene.text_overlay.strip())
        if expected not in prompt:
            raise ValueError(f"Trial prompt text does not match {scene.scene_id} callout.")
    elif NO_TEXT not in prompt:
        raise ValueError(f"Non-editorial trial prompt must prohibit text for {scene.scene_id}.")
    return f"{COMMON_STYLE} {prompt}"


def main() -> int:
    if not os.getenv("REPLICATE_API_TOKEN"):
        raise ValueError(
            "Set REPLICATE_API_TOKEN in the repository .env file before running this test."
        )
    storyboard = Storyboard.model_validate_json(
        STORYBOARD_FILE.read_text(encoding="utf-8")
    )
    scenes = {scene.scene_id: scene for scene in storyboard.scenes}
    missing = [scene_id for scene_id in TRIAL_SCENE_IDS if scene_id not in scenes]
    if missing:
        raise ValueError(f"Pilot storyboard is missing trial scenes: {', '.join(missing)}")

    manifest = TRIAL_DIRECTORY / "flux_schnell_prompt_test_manifest.json"
    assets_by_scene: dict[str, ImageAsset] = {}
    if manifest.is_file():
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8"))
            assets_by_scene = {
                asset.scene_id: asset
                for asset in (ImageAsset.model_validate(item) for item in existing)
                if asset.status == "completed" and asset.file_path
                and Path(asset.file_path).is_file()
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            assets_by_scene = {}

    engine = ImageEngine(ReplicateFluxSchnellProvider())
    for scene_id in TRIAL_SCENE_IDS:
        if scene_id in assets_by_scene:
            print(f"{scene_id}: reusing completed trial image")
            continue
        scene = scenes[scene_id]
        request = ImageGenerationRequest(
            image_id=scene.scene_id,
            scene_id=scene.scene_id,
            prompt=build_trial_prompt(scene),
            provider="replicate",
            output_directory=str(TRIAL_DIRECTORY),
        )
        assets_by_scene[scene_id] = engine.generate_asset(request)

    TRIAL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    assets = [assets_by_scene[scene_id] for scene_id in TRIAL_SCENE_IDS]
    manifest.write_text(
        json.dumps([asset.model_dump() for asset in assets], indent=2),
        encoding="utf-8",
    )
    for asset in assets:
        print(f"{asset.scene_id}: {asset.status} - {asset.file_path or asset.error_message}")
    print(f"Trial output: {TRIAL_DIRECTORY}")
    print(f"Manifest: {manifest}")
    return 0 if all(asset.status == "completed" for asset in assets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
