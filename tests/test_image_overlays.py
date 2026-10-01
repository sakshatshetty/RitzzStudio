import shutil
import subprocess
from pathlib import Path

import pytest

from modules.image.image_overlays import (
    FONT_CANDIDATES,
    create_thumbnail,
    embed_editorial_word,
)

FFMPEG = shutil.which("ffmpeg")
FONT = next((font for font in FONT_CANDIDATES if font.is_file()), None)
pytestmark = pytest.mark.skipif(
    FFMPEG is None or FONT is None,
    reason="FFmpeg and a supported font are required for image overlay tests.",
)


def make_png(path: Path) -> None:
    result = shutil.which("ffmpeg")
    assert result is not None
    subprocess_result = subprocess.run(
        [
            result,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=320x180",
            "-frames:v",
            "1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert subprocess_result.returncode == 0, subprocess_result.stderr


def test_editorial_word_is_composited_into_png(tmp_path: Path):
    image = tmp_path / "scene.png"
    make_png(image)
    original = image.read_bytes()

    result = embed_editorial_word(image, "HISTORY", ffmpeg_path=FFMPEG, font_path=FONT)

    assert result == image
    assert image.read_bytes() != original
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("word", ["", "TWO WORDS", "Mixed", "X" * 21])
def test_editorial_word_rejects_invalid_text(tmp_path: Path, word: str):
    image = tmp_path / "scene.png"
    make_png(image)

    with pytest.raises(ValueError, match="exactly one uppercase word"):
        embed_editorial_word(image, word, ffmpeg_path=FFMPEG, font_path=FONT)


def test_thumbnail_is_generated_at_youtube_dimensions(tmp_path: Path):
    source = tmp_path / "scene.png"
    output = tmp_path / "thumbnail.jpg"
    make_png(source)

    result = create_thumbnail(
        source,
        output,
        "Why Do Pirates Wear Eye Patches?",
        ffmpeg_path=FFMPEG,
        font_path=FONT,
    )

    assert result == output
    assert output.is_file() and output.stat().st_size > 0
    assert shutil.which("ffprobe") is not None
    dimensions = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert dimensions.stdout.strip() == "1280x720"
