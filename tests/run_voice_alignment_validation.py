import json
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

RESULT_FILE = (
    VOICE_DIR
    / "narration_result.json"
)

SCRIPT_FILE = (
    PROJECT_DIR
    / "script"
    / "script.json"
)

AUDIO_FILE = (
    VOICE_DIR
    / "narration.mp3"
)


# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

ALIGNMENT_END_TOLERANCE_SECONDS = 0.5
TIMESTAMP_TOLERANCE_SECONDS = 0.001


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def fail(message: str) -> NoReturn:
    """Raise a validation error and never return."""
    raise RuntimeError(message)


def load_json_file(
    file_path: Path,
    description: str,
) -> dict[str, Any]:
    """Load and validate a JSON object."""
    if not file_path.exists():
        fail(
            f"{description} not found: {file_path}"
        )

    try:
        raw_text = file_path.read_text(
            encoding="utf-8"
        )
        data: Any = json.loads(raw_text)

    except json.JSONDecodeError as exc:
        fail(
            f"{description} contains invalid JSON: {exc}"
        )

    if not isinstance(data, dict):
        fail(
            f"{description} must contain a JSON object."
        )

    return data


def get_required_string(
    data: dict[str, Any],
    key: str,
    description: str,
) -> str:
    """Get a required non-empty string."""
    value = data.get(key)

    if not isinstance(value, str):
        fail(
            f"{description} '{key}' must be a string."
        )

    value = value.strip()

    if not value:
        fail(
            f"{description} '{key}' cannot be empty."
        )

    return value


def get_required_float(
    data: dict[str, Any],
    key: str,
    description: str,
) -> float:
    """Get a required positive float."""
    value = data.get(key)

    if value is None:
        fail(
            f"{description} '{key}' is missing."
        )

    try:
        number = float(value)

    except (TypeError, ValueError):
        fail(
            f"{description} '{key}' must be numeric."
        )

    if number <= 0:
        fail(
            f"{description} '{key}' must be greater than zero."
        )

    return number


def get_required_list(
    data: dict[str, Any],
    key: str,
    description: str,
) -> list[Any]:
    """Get a required list."""
    value = data.get(key)

    if not isinstance(value, list):
        fail(
            f"{description} '{key}' must be a list."
        )

    if not value:
        fail(
            f"{description} '{key}' cannot be empty."
        )

    return value


# ---------------------------------------------------------------------
# Script validation
# ---------------------------------------------------------------------

def load_script_text() -> str:
    """
    Reconstruct the narration text from script.json.

    The project script stores narration inside sections.
    The narration generation used that script text, so this gives us
    an independent reference for character-count and text validation.
    """
    script = load_json_file(
        SCRIPT_FILE,
        "Script file",
    )

    sections_value = script.get(
        "sections"
    )

    if not isinstance(
        sections_value,
        list,
    ):
        fail(
            "Script 'sections' must be a list."
        )

    narration_parts: list[str] = []

    for index, section_value in enumerate(
        sections_value,
        start=1,
    ):
        if not isinstance(
            section_value,
            dict,
        ):
            fail(
                f"Script section {index} must be an object."
            )

        narration_value = section_value.get(
            "narration"
        )

        if not isinstance(
            narration_value,
            str,
        ):
            fail(
                f"Script section {index} narration must be a string."
            )

        narration = narration_value.strip()

        if not narration:
            fail(
                f"Script section {index} narration is empty."
            )

        narration_parts.append(
            narration
        )

    if not narration_parts:
        fail(
            "Script contains no narration sections."
        )

    return "\n\n".join(
        narration_parts
    )


# ---------------------------------------------------------------------
# Alignment extraction
# ---------------------------------------------------------------------

def extract_alignment(
    result: dict[str, Any],
) -> dict[str, Any]:
    """Extract ElevenLabs alignment data."""
    alignment_value = result.get(
        "alignment"
    )

    if alignment_value is None:
        fail(
            "Narration result does not contain alignment data."
        )

    if not isinstance(
        alignment_value,
        dict,
    ):
        fail(
            "Narration alignment must be a JSON object."
        )

    if not alignment_value:
        fail(
            "Narration alignment object is empty."
        )

    return alignment_value


def get_alignment_characters(
    alignment: dict[str, Any],
) -> list[str]:
    """Get the character sequence."""
    value = alignment.get(
        "characters"
    )

    if not isinstance(
        value,
        list,
    ):
        fail(
            "Alignment 'characters' must be a list."
        )

    if not value:
        fail(
            "Alignment 'characters' cannot be empty."
        )

    characters: list[str] = []

    for index, character in enumerate(
        value
    ):
        if not isinstance(
            character,
            str,
        ):
            fail(
                "Alignment character at index "
                f"{index} is not a string."
            )

        characters.append(
            character
        )

    return characters


def get_alignment_times(
    alignment: dict[str, Any],
) -> tuple[list[float], list[float]]:
    """Get character start and end timestamps."""
    start_value = alignment.get(
        "character_start_times_seconds"
    )

    end_value = alignment.get(
        "character_end_times_seconds"
    )

    if not isinstance(
        start_value,
        list,
    ):
        fail(
            "Alignment 'character_start_times_seconds' "
            "must be a list."
        )

    if not isinstance(
        end_value,
        list,
    ):
        fail(
            "Alignment 'character_end_times_seconds' "
            "must be a list."
        )

    if not start_value:
        fail(
            "Alignment start-time list cannot be empty."
        )

    if not end_value:
        fail(
            "Alignment end-time list cannot be empty."
        )

    starts: list[float] = []
    ends: list[float] = []

    for index, value in enumerate(
        start_value
    ):
        try:
            timestamp = float(value)

        except (TypeError, ValueError):
            fail(
                "Alignment start timestamp at index "
                f"{index} is not numeric."
            )

        starts.append(
            timestamp
        )

    for index, value in enumerate(
        end_value
    ):
        try:
            timestamp = float(value)

        except (TypeError, ValueError):
            fail(
                "Alignment end timestamp at index "
                f"{index} is not numeric."
            )

        ends.append(
            timestamp
        )

    return starts, ends


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------

def validate_alignment_lengths(
    characters: list[str],
    starts: list[float],
    ends: list[float],
) -> None:
    """Ensure all alignment arrays have equal lengths."""
    character_count = len(
        characters
    )

    start_count = len(
        starts
    )

    end_count = len(
        ends
    )

    if not (
        character_count
        == start_count
        == end_count
    ):
        fail(
            "Alignment array lengths do not match.\n"
            f"Characters: {character_count}\n"
            f"Start times: {start_count}\n"
            f"End times: {end_count}"
        )


def validate_timestamp_values(
    starts: list[float],
    ends: list[float],
) -> None:
    """Validate every timestamp."""
    previous_start = 0.0
    previous_end = 0.0

    for index, (
        start,
        end,
    ) in enumerate(
        zip(starts, ends)
    ):
        if start < 0:
            fail(
                f"Character {index} has a negative "
                f"start timestamp: {start}"
            )

        if end < 0:
            fail(
                f"Character {index} has a negative "
                f"end timestamp: {end}"
            )

        if end < start:
            fail(
                f"Character {index} has an end timestamp "
                f"before its start timestamp.\n"
                f"Start: {start}\n"
                f"End:   {end}"
            )

        if index > 0:
            if start < (
                previous_start
                - TIMESTAMP_TOLERANCE_SECONDS
            ):
                fail(
                    f"Character {index} start timestamp "
                    "moves backwards.\n"
                    f"Previous start: {previous_start}\n"
                    f"Current start:  {start}"
                )

            if end < (
                previous_end
                - TIMESTAMP_TOLERANCE_SECONDS
            ):
                fail(
                    f"Character {index} end timestamp "
                    "moves backwards.\n"
                    f"Previous end: {previous_end}\n"
                    f"Current end:  {end}"
                )

        previous_start = start
        previous_end = end


def validate_alignment_duration(
    starts: list[float],
    ends: list[float],
    audio_duration: float,
) -> None:
    """Ensure alignment finishes near the actual audio duration."""
    if not starts or not ends:
        fail(
            "Alignment contains no timestamps."
        )

    first_start = starts[0]
    final_end = ends[-1]

    if abs(first_start) > ALIGNMENT_END_TOLERANCE_SECONDS:
        fail(
            "Alignment does not start near zero.\n"
            f"First start: {first_start:.3f}s"
        )

    difference = abs(
        final_end
        - audio_duration
    )

    if difference > ALIGNMENT_END_TOLERANCE_SECONDS:
        fail(
            "Final alignment timestamp does not match "
            "the actual MP3 duration.\n"
            f"Final alignment end: {final_end:.3f}s\n"
            f"Audio duration:       {audio_duration:.3f}s\n"
            f"Difference:           {difference:.3f}s\n"
            f"Allowed:              "
            f"{ALIGNMENT_END_TOLERANCE_SECONDS:.3f}s"
        )


def validate_alignment_text(
    alignment_characters: list[str],
    script_text: str,
) -> None:
    """
    Compare alignment character sequence against script text.

    ElevenLabs documents 'alignment' as timing information for
    characters in the original text, while normalized_alignment is
    for normalized text. Therefore the original alignment should
    correspond to the text submitted for generation.
    """
    alignment_text = "".join(
        alignment_characters
    )

    if alignment_text == script_text:
        return

    if (
        alignment_text.strip()
        == script_text.strip()
    ):
        return

    minimum_length = min(
        len(alignment_text),
        len(script_text),
    )

    mismatch_index: int | None = None

    for index in range(
        minimum_length
    ):
        if alignment_text[index] != script_text[index]:
            mismatch_index = index
            break

    if mismatch_index is None:
        mismatch_index = minimum_length

    start = max(
        0,
        mismatch_index - 30,
    )

    end = min(
        minimum_length,
        mismatch_index + 30,
    )

    alignment_context = alignment_text[
        start:end
    ]

    script_context = script_text[
        start:end
    ]

    fail(
        "Alignment characters do not match "
        "the source script text.\n"
        f"Mismatch index: {mismatch_index}\n"
        f"Alignment:      {alignment_context!r}\n"
        f"Script:         {script_context!r}"
    )


def validate_saved_counts(
    result: dict[str, Any],
    alignment_character_count: int,
) -> None:
    """Validate saved character metadata when present."""
    character_count_value = result.get(
        "character_count"
    )

    aligned_characters_value = result.get(
        "aligned_characters"
    )

    if character_count_value is not None:
        try:
            character_count = int(
                character_count_value
            )

        except (TypeError, ValueError):
            fail(
                "'character_count' must be an integer."
            )

        if character_count != alignment_character_count:
            fail(
                "Saved character_count does not match "
                "alignment character count.\n"
                f"Saved:      {character_count}\n"
                f"Alignment:  {alignment_character_count}"
            )

    if aligned_characters_value is not None:
        try:
            aligned_characters = int(
                aligned_characters_value
            )

        except (TypeError, ValueError):
            fail(
                "'aligned_characters' must be an integer."
            )

        if aligned_characters != alignment_character_count:
            fail(
                "Saved aligned_characters does not match "
                "alignment character count.\n"
                f"Saved:      {aligned_characters}\n"
                f"Alignment:  {alignment_character_count}"
            )


def load_actual_audio_duration() -> float:
    """
    Read actual MP3 duration using ffprobe.

    Milestone 20 has already validated ffprobe availability and
    the MP3 itself. We use the same approach here so the alignment
    endpoint is checked against the real audio duration.
    """
    import shutil
    import subprocess

    ffprobe = shutil.which(
        "ffprobe"
    )

    if ffprobe is None:
        fail(
            "ffprobe was not found on PATH."
        )

    if not AUDIO_FILE.exists():
        fail(
            f"Audio file not found: {AUDIO_FILE}"
        )

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(AUDIO_FILE),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        fail(
            "ffprobe failed while reading "
            "the narration MP3.\n"
            f"{completed.stderr.strip()}"
        )

    raw_duration = completed.stdout.strip()

    if not raw_duration:
        fail(
            "ffprobe returned no audio duration."
        )

    try:
        duration = float(
            raw_duration
        )

    except ValueError:
        fail(
            "ffprobe returned a non-numeric "
            "audio duration."
        )

    if duration <= 0:
        fail(
            "Actual audio duration must be greater than zero."
        )

    return duration


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("RITZZ — MILESTONE 21")
    print("ACTUAL TIMESTAMP / ALIGNMENT VALIDATION")
    print("=" * 70)
    print()

    print(
        f"Result file: {RESULT_FILE}"
    )

    result = load_json_file(
        RESULT_FILE,
        "Narration result file",
    )

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

    # -------------------------------------------------------------
    # Load source script
    # -------------------------------------------------------------

    script_text = load_script_text()

    print(
        f"Script characters:        {len(script_text):,}"
    )

    # -------------------------------------------------------------
    # Extract alignment
    # -------------------------------------------------------------

    alignment = extract_alignment(
        result
    )

    characters = get_alignment_characters(
        alignment
    )

    starts, ends = get_alignment_times(
        alignment
    )

    print(
        f"Alignment characters:     {len(characters):,}"
    )

    validate_alignment_lengths(
        characters,
        starts,
        ends,
    )

    print(
        "Alignment array lengths:  PASS"
    )

    # -------------------------------------------------------------
    # Timestamp validation
    # -------------------------------------------------------------

    validate_timestamp_values(
        starts,
        ends,
    )

    print(
        "Timestamp ordering:       PASS"
    )

    print(
        "Timestamp values:         PASS"
    )

    # -------------------------------------------------------------
    # Audio duration comparison
    # -------------------------------------------------------------

    audio_duration = load_actual_audio_duration()

    final_alignment_end = ends[-1]

    validate_alignment_duration(
        starts,
        ends,
        audio_duration,
    )

    print(
        f"Audio duration:           "
        f"{audio_duration:.3f} seconds"
    )

    print(
        f"Final alignment end:      "
        f"{final_alignment_end:.3f} seconds"
    )

    print(
        "Alignment/audio match:    PASS"
    )

    # -------------------------------------------------------------
    # Text validation
    # -------------------------------------------------------------

    validate_alignment_text(
        characters,
        script_text,
    )

    print(
        "Alignment source text:    PASS"
    )

    # -------------------------------------------------------------
    # Saved metadata
    # -------------------------------------------------------------

    validate_saved_counts(
        result,
        len(characters),
    )

    print(
        "Saved character counts:   PASS"
    )

    # -------------------------------------------------------------
    # Final report
    # -------------------------------------------------------------

    first_start = starts[0]
    last_end = ends[-1]

    print()
    print("=" * 70)
    print("TIMESTAMP / ALIGNMENT VALIDATION COMPLETE")
    print("=" * 70)

    print(
        f"Character count:          {len(characters):,}"
    )

    print(
        f"Start timestamp:          {first_start:.3f}s"
    )

    print(
        f"Final timestamp:          {last_end:.3f}s"
    )

    print(
        f"Audio duration:           {audio_duration:.3f}s"
    )

    print(
        f"Alignment difference:     "
        f"{last_end - audio_duration:+.3f}s"
    )

    print()
    print(
        "Milestone 21 validation passed."
    )

    print(
        "Character-level timestamps are ready "
        "for narration-to-scene synchronization."
    )


if __name__ == "__main__":
    main()