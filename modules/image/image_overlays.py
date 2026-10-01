from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
)

THUMBNAIL_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "did", "do", "does", "for",
    "from", "how", "in", "is", "it", "of", "on", "the", "this", "to",
    "was", "were", "what", "when", "where", "which", "who", "why",
}


def _resolve_ffmpeg(ffmpeg_path: str | None = None) -> str:
    resolved = ffmpeg_path or os.getenv("RITZZ_FFMPEG_PATH") or shutil.which("ffmpeg")
    if not resolved:
        raise FileNotFoundError(
            "FFmpeg is required to composite image text. Install FFmpeg or configure RITZZ_FFMPEG_PATH."
        )
    return resolved


def _resolve_font(font_path: str | Path | None = None) -> Path:
    configured = font_path or os.getenv("RITZZ_FONT_PATH")
    if configured:
        resolved = Path(configured)
        if not resolved.is_file():
            raise FileNotFoundError(f"Configured font file does not exist: {resolved}")
        return resolved

    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "No supported bold font was found. Set RITZZ_FONT_PATH to a font file."
    )


def _escape_filter_path(path: Path) -> str:
    return (
        path.resolve().as_posix()
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


def _run_drawtext(
    source_image: Path,
    output_image: Path,
    text: str,
    *,
    resize_filter: str | None = None,
    ffmpeg_path: str | None = None,
    font_path: str | Path | None = None,
) -> Path:
    if not source_image.is_file() or source_image.stat().st_size == 0:
        raise FileNotFoundError(f"Source image is missing or empty: {source_image}")
    if not text.strip():
        raise ValueError("Overlay text cannot be blank.")

    ffmpeg = _resolve_ffmpeg(ffmpeg_path)
    font = _resolve_font(font_path)
    output_image.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ritzz_image_overlay_") as temporary:
        temporary_path = Path(temporary)
        text_file = temporary_path / "overlay.txt"
        candidate = temporary_path / output_image.name
        text_file.write_text(text.strip(), encoding="utf-8")
        filters = []
        if resize_filter:
            filters.append(resize_filter)
        filters.append(
            "drawtext="
            f"fontfile='{_escape_filter_path(font)}':"
            f"textfile='{_escape_filter_path(text_file)}':"
            "expansion=none:fontsize=h/12:fontcolor=white:"
            "box=1:boxcolor=black@0.72:boxborderw=18:"
            "borderw=2:bordercolor=black:"
            "x=w/16:y=h-text_h-h/16"
        )
        command = [
            ffmpeg,
            "-v", "error",
            "-y",
            "-i", str(source_image),
            "-vf", ",".join(filters),
            "-frames:v", "1",
            "-update", "1",
            str(candidate),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"FFmpeg text composition failed for {source_image}: {completed.stderr.strip()}"
            )
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg did not create the expected image: {candidate}")
        candidate.replace(output_image)
    return output_image


def embed_editorial_word(
    image_path: str | Path,
    word: str,
    *,
    ffmpeg_path: str | None = None,
    font_path: str | Path | None = None,
) -> Path:
    cleaned = word.strip()
    if (
        not cleaned
        or len(cleaned.split()) != 1
        or not cleaned.isupper()
        or len(cleaned) > 20
    ):
        raise ValueError("Editorial overlay must be exactly one uppercase word of at most 20 characters.")

    output = Path(image_path)
    with tempfile.TemporaryDirectory(prefix="ritzz_editorial_") as temporary:
        candidate = Path(temporary) / output.name
        _run_drawtext(
            output,
            candidate,
            cleaned,
            ffmpeg_path=ffmpeg_path,
            font_path=font_path,
        )
        candidate.replace(output)
    return output


def create_thumbnail(
    source_image: str | Path,
    output_image: str | Path,
    title: str,
    *,
    ffmpeg_path: str | None = None,
    font_path: str | Path | None = None,
) -> Path:
    words = [
        word
        for word in re.findall(r"[A-Za-z0-9]+", title)
        if word.casefold() not in THUMBNAIL_STOP_WORDS
    ]
    headline = " ".join(words[:3]).upper()
    if not headline:
        raise ValueError("A title with at least one meaningful word is required for the thumbnail.")
    return _run_drawtext(
        Path(source_image),
        Path(output_image),
        headline,
        resize_filter="scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
        ffmpeg_path=ffmpeg_path,
        font_path=font_path,
    )
