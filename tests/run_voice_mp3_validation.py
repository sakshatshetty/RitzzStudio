import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn


# ---------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------
# Project files
# ---------------------------------------------------------------------

PROJECT_DIR = (
    PROJECT_ROOT
    / "projects"
    / "20260820_001_why_do_pirates_wear_eye_patches"
)

VOICE_DIR = PROJECT_DIR / "voice"

RESULT_FILE = VOICE_DIR / "narration_result.json"

DEFAULT_AUDIO_FILE = VOICE_DIR / "narration.mp3"


# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

DEFAULT_TARGET_DURATION_SECONDS = 480.0
DURATION_TOLERANCE_SECONDS = 0.5


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def fail(message: str) -> NoReturn:
    """Raise a validation error and never return."""
    raise RuntimeError(message)


def load_result() -> dict[str, Any]:
    """Load narration_result.json."""
    if not RESULT_FILE.exists():
        fail(
            f"Voice result file not found: {RESULT_FILE}"
        )

    try:
        raw_data = RESULT_FILE.read_text(
            encoding="utf-8"
        )

        data: Any = json.loads(raw_data)

    except json.JSONDecodeError as exc:
        fail(
            f"Voice result JSON is invalid: {exc}"
        )

    if not isinstance(data, dict):
        fail(
            "Voice result JSON must contain a JSON object."
        )

    return data


def resolve_audio_file(
    result: dict[str, Any],
) -> Path:
    """Resolve the generated narration MP3 path."""
    result_path_value = result.get("file_path")

    if isinstance(result_path_value, str):
        result_path = Path(
            result_path_value
        )

        if result_path.exists():
            return result_path

        if not result_path.is_absolute():
            project_relative_path = (
                PROJECT_ROOT / result_path
            )

            if project_relative_path.exists():
                return project_relative_path

    if DEFAULT_AUDIO_FILE.exists():
        return DEFAULT_AUDIO_FILE

    fail(
        "Narration MP3 could not be found.\n"
        f"Expected default path: {DEFAULT_AUDIO_FILE}"
    )


def get_ffprobe_path() -> str:
    """Find ffprobe on PATH."""
    ffprobe_path = shutil.which(
        "ffprobe"
    )

    if ffprobe_path is None:
        fail(
            "ffprobe was not found on PATH.\n"
            "Install FFmpeg and ensure ffprobe is available "
            "from PowerShell."
        )

    return ffprobe_path


def probe_audio(
    audio_file: Path,
) -> dict[str, Any]:
    """Read audio metadata using ffprobe."""
    ffprobe = get_ffprobe_path()

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-show_entries",
        "stream=codec_type,codec_name,duration",
        "-of",
        "json",
        str(audio_file),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        error_message = (
            completed.stderr.strip()
            or "Unknown ffprobe error."
        )

        fail(
            "ffprobe could not read the MP3.\n"
            f"{error_message}"
        )

    try:
        data: Any = json.loads(
            completed.stdout
        )

    except json.JSONDecodeError as exc:
        fail(
            f"ffprobe returned invalid JSON: {exc}"
        )

    if not isinstance(data, dict):
        fail(
            "ffprobe output is not a JSON object."
        )

    return data


def extract_actual_duration(
    probe_data: dict[str, Any],
) -> float:
    """Extract actual MP3 duration from ffprobe."""
    format_data = probe_data.get(
        "format"
    )

    if not isinstance(
        format_data,
        dict,
    ):
        fail(
            "ffprobe output does not contain format metadata."
        )

    duration_value = format_data.get(
        "duration"
    )

    if duration_value is None:
        fail(
            "Actual audio duration is missing from ffprobe output."
        )

    try:
        duration = float(
            duration_value
        )

    except (TypeError, ValueError):
        fail(
            "Actual audio duration is not numeric."
        )

    if duration <= 0:
        fail(
            "Actual audio duration must be greater than zero."
        )

    return duration


def validate_audio_stream(
    probe_data: dict[str, Any],
) -> None:
    """Validate that an MP3 audio stream exists."""
    streams_value = probe_data.get(
        "streams"
    )

    if not isinstance(
        streams_value,
        list,
    ):
        fail(
            "ffprobe did not return stream information."
        )

    audio_streams: list[dict[str, Any]] = []

    for stream_value in streams_value:
        if not isinstance(
            stream_value,
            dict,
        ):
            continue

        codec_type = stream_value.get(
            "codec_type"
        )

        if codec_type == "audio":
            audio_streams.append(
                stream_value
            )

    if not audio_streams:
        fail(
            "The generated file does not contain an audio stream."
        )

    codec_names: list[str] = []

    for stream in audio_streams:
        codec_name = stream.get(
            "codec_name"
        )

        if isinstance(
            codec_name,
            str,
        ):
            codec_names.append(
                codec_name
            )

    if "mp3" not in codec_names:
        fail(
            "The generated file does not contain "
            "an MP3 audio codec.\n"
            f"Detected codecs: {codec_names}"
        )


def get_numeric_result_value(
    result: dict[str, Any],
    key: str,
) -> float:
    """Read a required numeric value from the result JSON."""
    value = result.get(key)

    if value is None:
        fail(
            f"narration_result.json does not contain "
            f"'{key}'."
        )

    try:
        numeric_value = float(
            value
        )

    except (TypeError, ValueError):
        fail(
            f"'{key}' in narration_result.json "
            "is not numeric."
        )

    return numeric_value


def validate_result_duration(
    result: dict[str, Any],
    actual_duration: float,
) -> float:
    """Validate saved duration against actual MP3 duration."""
    result_duration = get_numeric_result_value(
        result,
        "duration_seconds",
    )

    if result_duration <= 0:
        fail(
            "Saved narration duration must be greater than zero."
        )

    difference = abs(
        actual_duration
        - result_duration
    )

    if difference > DURATION_TOLERANCE_SECONDS:
        fail(
            "Saved narration duration does not match "
            "the actual MP3 duration.\n"
            f"Saved duration:  {result_duration:.2f}s\n"
            f"Actual duration: {actual_duration:.2f}s\n"
            f"Difference:      {difference:.2f}s\n"
            f"Allowed:         {DURATION_TOLERANCE_SECONDS:.2f}s"
        )

    return result_duration


def get_optional_integer(
    result: dict[str, Any],
    key: str,
) -> int | None:
    """Read an optional integer value."""
    value = result.get(key)

    if value is None:
        return None

    try:
        integer_value = int(
            value
        )

    except (TypeError, ValueError):
        fail(
            f"'{key}' must be an integer."
        )

    if integer_value <= 0:
        fail(
            f"'{key}' must be greater than zero."
        )

    return integer_value


def validate_character_counts(
    result: dict[str, Any],
) -> tuple[int | None, int | None]:
    """Validate character counts when present."""
    character_count = get_optional_integer(
        result,
        "character_count",
    )

    aligned_characters = get_optional_integer(
        result,
        "aligned_characters",
    )

    if (
        character_count is not None
        and aligned_characters is not None
        and character_count
        != aligned_characters
    ):
        fail(
            "Character count and aligned-character "
            "count do not match.\n"
            f"Characters:         {character_count}\n"
            f"Aligned characters: {aligned_characters}"
        )

    return (
        character_count,
        aligned_characters,
    )


def validate_alignment(
    result: dict[str, Any],
) -> None:
    """Validate that alignment data exists."""
    if "alignment" not in result:
        fail(
            "Narration result does not contain alignment data."
        )

    alignment = result.get(
        "alignment"
    )

    if alignment is None:
        fail(
            "Narration alignment is missing."
        )

    if not isinstance(
        alignment,
        dict,
    ):
        fail(
            "Narration alignment must be a JSON object."
        )

    if not alignment:
        fail(
            "Narration alignment object is empty."
        )


def get_target_duration(
    result: dict[str, Any],
) -> float:
    """Get target duration with a safe default."""
    value = result.get(
        "target_duration_seconds"
    )

    if value is None:
        return DEFAULT_TARGET_DURATION_SECONDS

    try:
        target_duration = float(
            value
        )

    except (TypeError, ValueError):
        return DEFAULT_TARGET_DURATION_SECONDS

    if target_duration <= 0:
        return DEFAULT_TARGET_DURATION_SECONDS

    return target_duration


# ---------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("RITZZ — MILESTONE 20")
    print("ACTUAL VOICE MP3 VALIDATION")
    print("=" * 70)
    print()

    print(
        f"Result file: {RESULT_FILE}"
    )

    result = load_result()

    status = result.get(
        "status"
    )

    if status != "completed":
        fail(
            "Narration result status is not 'completed'.\n"
            f"Status: {status}"
        )

    print(
        "Result status: completed"
    )

    audio_file = resolve_audio_file(
        result
    )

    print(
        f"Audio file: {audio_file}"
    )

    if not audio_file.exists():
        fail(
            f"Audio file does not exist: {audio_file}"
        )

    file_size = audio_file.stat().st_size

    if file_size <= 0:
        fail(
            "Audio file is empty."
        )

    print(
        f"Audio size: {file_size:,} bytes"
    )

    # -------------------------------------------------------------
    # Actual audio inspection
    # -------------------------------------------------------------

    probe_data = probe_audio(
        audio_file
    )

    validate_audio_stream(
        probe_data
    )

    actual_duration = extract_actual_duration(
        probe_data
    )

    # -------------------------------------------------------------
    # Saved metadata validation
    # -------------------------------------------------------------

    saved_duration = validate_result_duration(
        result,
        actual_duration,
    )

    (
        character_count,
        aligned_characters,
    ) = validate_character_counts(
        result
    )

    validate_alignment(
        result
    )

    target_duration = get_target_duration(
        result
    )

    target_difference = (
        actual_duration
        - target_duration
    )

    # -------------------------------------------------------------
    # Report
    # -------------------------------------------------------------

    print()
    print("=" * 70)
    print("VOICE MP3 VALIDATION COMPLETE")
    print("=" * 70)

    print(
        "MP3 readable:             PASS"
    )

    print(
        "Audio stream:             PASS"
    )

    print(
        "Codec:                    mp3"
    )

    print(
        f"Actual duration:          "
        f"{actual_duration:.2f} seconds"
    )

    print(
        f"Saved result duration:    "
        f"{saved_duration:.2f} seconds"
    )

    print(
        "Duration metadata match:  PASS"
    )

    if character_count is not None:
        print(
            f"Characters:               "
            f"{character_count:,}"
        )

    if aligned_characters is not None:
        print(
            f"Aligned characters:       "
            f"{aligned_characters:,}"
        )

    print(
        "Alignment data:            PASS"
    )

    print(
        f"Target duration:           "
        f"{target_duration:.2f} seconds"
    )

    print(
        f"Target difference:         "
        f"{target_difference:+.2f} seconds"
    )

    print()
    print(
        "Milestone 20 validation passed."
    )

    print(
        "The actual MP3 duration will be used "
        "as the real audio timing reference "
        "for later video synchronization."
    )


if __name__ == "__main__":
    main()