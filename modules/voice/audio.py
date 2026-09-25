"""Audio probing helpers shared by narration workflows."""

import math
import os
import shutil
import subprocess
from pathlib import Path


def probe_audio_duration(audio_path: str | Path) -> float:
    """Return the measured media duration using FFprobe."""

    configured = os.getenv("RITZZ_FFPROBE_PATH")
    executable = configured or shutil.which("ffprobe")
    if not executable:
        raise RuntimeError(
            "FFprobe was not found. Set RITZZ_FFPROBE_PATH to ffprobe.exe."
        )

    completed = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        duration = float(completed.stdout.strip())
    except ValueError as exc:
        raise ValueError(
            f"FFprobe returned an invalid duration for {audio_path}."
        ) from exc

    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(
            f"FFprobe returned a non-positive duration for {audio_path}."
        )
    return duration
