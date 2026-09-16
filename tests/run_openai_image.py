from pathlib import Path

from modules.image.engine import ImageEngine
from modules.image.providers.openai import OpenAIImageProvider


OUTPUT_DIRECTORY = Path("projects") / "image_consistency_test"

BASE_STYLE = (
    "Simple 2D stickman cartoon illustration, "
    "thick black outlines, flat colors, very minimal shading, "
    "large clear shapes, simple expressive character, "
    "minimal visual detail, generous negative space, "
    "clean uncluttered composition, "
    "YouTube explainer animation style. "
    "Landscape 16:9 composition."
)

NEGATIVE_STYLE = (
    "Avoid photorealism, realistic humans, 3D rendering, "
    "detailed textures, intricate clothing, ornate objects, "
    "busy backgrounds, tiny details, visual clutter, "
    "watermarks, logos, and unnecessary text."
)


SCENES = [
    {
        "image_id": "pirate_consistency_001",
        "description": (
            "A friendly simple stickman pirate standing on the deck "
            "of a classic sailing ship, looking through a telescope "
            "toward the ocean. A simple ship wheel is visible nearby. "
            "Blue ocean and sky in the background."
        ),
    },
    {
        "image_id": "pirate_consistency_002",
        "description": (
            "The same friendly simple stickman pirate walking across "
            "the deck of the same classic sailing ship. The pirate "
            "wears the same eye patch, pirate hat, and simple pirate "
            "clothing. Two simple barrels are visible nearby. "
            "Blue ocean and sky in the background."
        ),
    },
    {
        "image_id": "pirate_consistency_003",
        "description": (
            "The same friendly simple stickman pirate standing beside "
            "a simple wooden treasure chest on the deck of the same "
            "classic sailing ship. The pirate wears the same eye patch, "
            "pirate hat, and simple pirate clothing. Blue ocean and "
            "sky in the background."
        ),
    },
]


def main() -> None:
    provider = OpenAIImageProvider()
    engine = ImageEngine(provider)

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    for scene in SCENES:
        prompt = (
            f"{BASE_STYLE} "
            f"{scene['description']} "
            f"Keep the character design visually consistent across "
            f"all images in this test. "
            f"{NEGATIVE_STYLE}"
        )

        request = engine.create_request(
            image_id=scene["image_id"],
            scene_id=scene["image_id"],
            prompt=prompt,
            output_directory=OUTPUT_DIRECTORY,
        )

        print(f"\nGenerating {scene['image_id']}...")
        print(f"Size: {request.width}x{request.height}")

        result = engine.generate(request)

        print(f"Status: {result.status}")

        if result.file_path:
            print(f"File: {result.file_path}")

        if result.error_message:
            print(f"Error: {result.error_message}")


if __name__ == "__main__":
    main()