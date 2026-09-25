"""Generate an isolated two-minute calm narration audio test."""

import json
import os
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from modules.voice.elevenlabs import ElevenLabsProvider
from modules.voice.engine import VoiceEngine
from modules.voice.models import VoiceGenerationRequest, VoiceSettings
from modules.voice.pilot import PilotNarrationEngine

OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "projects"
    / "20260820_001_why_do_pirates_wear_eye_patches"
    / "pilot_3min"
    / "audio_tests"
    / "calm_delivery_2min"
)
SCRIPT_FILE = (
    PROJECT_ROOT
    / "projects"
    / "20260820_001_why_do_pirates_wear_eye_patches"
    / "pilot_3min"
    / "audio_tests"
    / "calm_delivery_2min_script.txt"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an isolated calm narration audio take")
    parser.add_argument(
        "--take-name",
        default="calm_delivery_2min",
        help="Name used for the separate output folder and MP3 file",
    )
    args = parser.parse_args()
    if not args.take_name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("take-name may contain only letters, numbers, underscores, and hyphens.")

    load_dotenv(PROJECT_ROOT / ".env", override=True)
    voice_id = os.getenv("RITZZ_VOICE_ID")
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not voice_id:
        raise ValueError("RITZZ_VOICE_ID is not configured.")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY is not configured.")

    text = SCRIPT_FILE.read_text(encoding="utf-8").strip()
    request = VoiceGenerationRequest(
        voice_id=voice_id,
        model_id="eleven_multilingual_v2",
        text=text,
        output_directory=str(OUTPUT_DIRECTORY.parent / args.take_name),
        output_filename=f"{args.take_name}.mp3",
        voice_settings=VoiceSettings(
            stability=0.72,
            similarity_boost=0.75,
            style=0.0,
            use_speaker_boost=True,
            speed=0.95,
        ),
    )
    result = ElevenLabsProvider(api_key=api_key).generate(request)
    if result.status != "completed" or not result.file_path:
        raise RuntimeError(
            f"Narration generation failed: {result.error_message or 'unknown error'}"
        )
    if not result.alignment or not result.alignment.characters:
        raise RuntimeError("ElevenLabs did not return character timestamps.")

    audio_path = Path(result.file_path)
    result.actual_duration_seconds = PilotNarrationEngine.probe_audio_duration(audio_path)
    output_directory = Path(request.output_directory)
    VoiceEngine.save_result(result, output_directory / f"{args.take_name}_result.json")
    (output_directory / "voice_settings.json").write_text(
        json.dumps(request.voice_settings.model_dump(), indent=2), encoding="utf-8"
    )
    print(f"Audio: {audio_path}")
    print(f"Measured duration: {result.actual_duration_seconds:.3f}s")
    print(f"Script words: {len(text.split())}")
    print(f"Aligned characters: {len(result.alignment.characters)}")
    print(f"Metadata: {output_directory / f'{args.take_name}_result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
