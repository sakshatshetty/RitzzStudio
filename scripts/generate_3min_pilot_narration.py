import os
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from modules.voice.elevenlabs import ElevenLabsProvider
from modules.voice.pilot import PilotNarrationEngine

load_dotenv(PROJECT_ROOT / ".env")

PILOT_DIRECTORY = PROJECT_ROOT / "projects" / "20260820_001_why_do_pirates_wear_eye_patches" / "pilot_3min"
STORYBOARD_FILE = PILOT_DIRECTORY / "storyboard_dynamic.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate dedicated pilot narration")
    parser.add_argument("--minimum-seconds", type=float, default=180.0,
                        help="Required minimum measured audio duration (default: 180 seconds)")
    args = parser.parse_args()
    voice_id = os.getenv("RITZZ_VOICE_ID")
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not voice_id:
        raise ValueError("RITZZ_VOICE_ID is not configured.")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY is not configured.")
    result = PilotNarrationEngine(ElevenLabsProvider(api_key=api_key)).generate(
        STORYBOARD_FILE, PILOT_DIRECTORY, voice_id,
        minimum_duration_seconds=args.minimum_seconds,
    )
    print(f"Pilot narration: {result.file_path}")
    print(f"Measured audio duration: {result.actual_duration_seconds:.3f}s")
    print(f"Aligned characters: {len(result.alignment.characters) if result.alignment else 0}")
    print(f"Timestamps: {PILOT_DIRECTORY / PilotNarrationEngine.RESULT_FILENAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
