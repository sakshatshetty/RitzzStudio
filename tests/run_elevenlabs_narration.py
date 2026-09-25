import os
import sys
from pathlib import Path


# Allow direct execution with:
# python tests/run_elevenlabs_narration.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from dotenv import load_dotenv

from modules.voice.elevenlabs import ElevenLabsProvider
from modules.voice.engine import NarrationTooShortError, VoiceEngine


load_dotenv()


PROJECT_DIR = (
    PROJECT_ROOT
    / "projects"
    / "20260820_001_why_do_pirates_wear_eye_patches"
)

SCRIPT_FILE = (
    PROJECT_DIR
    / "script"
    / "script.json"
)

OUTPUT_DIR = PROJECT_DIR / "voice"

OUTPUT_FILENAME = "narration.mp3"

RESULT_FILE = (
    OUTPUT_DIR
    / "narration_result.json"
)

VOICE_ID_ENV = "RITZZ_VOICE_ID"

MODEL_ID = "eleven_multilingual_v2"


def main() -> None:
    print()
    print("RITZZ — MILESTONE 19")
    print("ACTUAL ELEVENLABS SCRIPT NARRATION")
    print("=" * 70)
    print()

    # ---------------------------------------------------------
    # Validate environment
    # ---------------------------------------------------------

    voice_id = os.getenv(VOICE_ID_ENV)

    if not voice_id:
        raise ValueError(
            f"{VOICE_ID_ENV} is not configured in .env."
        )

    api_key = os.getenv(
        "ELEVENLABS_API_KEY"
    )

    if not api_key:
        raise ValueError(
            "ELEVENLABS_API_KEY is not configured in .env."
        )

    print(
        f"Voice ID: configured via {VOICE_ID_ENV}"
    )
    print(
        f"Voice model: {MODEL_ID}"
    )
    print()

    # ---------------------------------------------------------
    # Validate script
    # ---------------------------------------------------------

    if not SCRIPT_FILE.exists():
        raise FileNotFoundError(
            f"Script file not found: {SCRIPT_FILE}"
        )

    print(
        f"Script: {SCRIPT_FILE}"
    )

    # ---------------------------------------------------------
    # Initialize provider and engine
    # ---------------------------------------------------------

    provider = ElevenLabsProvider(
        api_key=api_key
    )

    engine = VoiceEngine(
        provider
    )

    # ---------------------------------------------------------
    # Load script and inspect narration
    # ---------------------------------------------------------

    script = engine.load_script(
        SCRIPT_FILE
    )

    request = engine.create_request(
        script=script,
        voice_id=voice_id,
        output_directory=OUTPUT_DIR,
        output_filename=OUTPUT_FILENAME,
        model_id=MODEL_ID,
    )

    print(
        f"Topic: {script.topic}"
    )

    print(
        f"Target duration: "
        f"{script.target_duration_seconds} seconds"
    )

    print(
        f"Narration characters: "
        f"{len(request.text)}"
    )

    print()

    # ---------------------------------------------------------
    # Generate actual narration
    # ---------------------------------------------------------

    print(
        "Sending script to ElevenLabs..."
    )

    print(
        "This is the REAL production narration."
    )

    print()

    # Remove stale alignment metadata so an older successful take cannot be
    # synchronized with a newly generated short audio file.
    RESULT_FILE.unlink(missing_ok=True)
    try:
        result = engine.generate(request)
    except NarrationTooShortError as exc:
        engine.save_result(exc.result, RESULT_FILE)
        raise

    # ---------------------------------------------------------
    # Validate generation
    # ---------------------------------------------------------

    if result.status != "completed":
        raise RuntimeError(
            "ElevenLabs narration generation failed: "
            f"{result.error_message}"
        )

    if not result.file_path:
        raise RuntimeError(
            "Narration completed but no audio "
            "file path was returned."
        )

    if result.duration_seconds is None:
        raise RuntimeError(
            "Narration completed but no duration "
            "was returned."
        )

    if result.duration_seconds <= 0:
        raise RuntimeError(
            "Narration completed with invalid duration."
        )

    output_path = Path(
        result.file_path
    )

    if not output_path.exists():
        raise RuntimeError(
            f"Generated narration file does not exist: "
            f"{output_path}"
        )

    if output_path.stat().st_size == 0:
        raise RuntimeError(
            f"Generated narration file is empty: "
            f"{output_path}"
        )

    # ---------------------------------------------------------
    # Save result metadata
    # ---------------------------------------------------------

    engine.save_result(
        result=result,
        output_file=RESULT_FILE,
    )

    # ---------------------------------------------------------
    # Display result
    # ---------------------------------------------------------

    print("=" * 70)
    print("NARRATION GENERATION COMPLETE")
    print("=" * 70)
    print()

    print(
        f"Audio file: {output_path}"
    )

    print(
        f"Audio size: "
        f"{output_path.stat().st_size:,} bytes"
    )

    print(
        f"Duration: "
        f"{result.actual_duration_seconds:.2f} seconds"
    )

    print(
        f"Characters: "
        f"{result.character_count:,}"
    )

    if result.alignment is not None:
        print(
            "Alignment: available"
        )

        print(
            "Aligned characters: "
            f"{len(result.alignment.characters):,}"
        )
    else:
        print(
            "Alignment: not available"
        )

    print(
        f"Result metadata: {RESULT_FILE}"
    )

    print()

    print(
        "Milestone 19 production narration "
        "has been generated successfully."
    )

    print()


if __name__ == "__main__":
    main()
