from types import SimpleNamespace
import struct
import zlib

import pytest

from modules.video import image_asset_qa
from modules.video.image_asset_qa import image_similarity, inspect_image_asset


TSV_HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\t"
    "width\theight\tconf\ttext\n"
)


def _word_row(confidence: int, text: str) -> str:
    return f"5\t1\t1\t1\t1\t1\t0\t0\t20\t10\t{confidence}\t{text}\n"


def write_solid_png(path, color: tuple[int, int, int]) -> None:
    width = height = 16
    scanline = bytes(color) * width
    raw = b"".join(b"\x00" + scanline for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_perceptual_hash_distinguishes_flat_images_with_different_colors(tmp_path) -> None:
    red = tmp_path / "red.png"
    blue = tmp_path / "blue.png"
    write_solid_png(red, (220, 30, 30))
    write_solid_png(blue, (30, 30, 220))

    red_hash = inspect_image_asset(red).difference_hash
    blue_hash = inspect_image_asset(blue).difference_hash

    assert image_similarity(red_hash, blue_hash) < 0.97


def test_perceptual_hash_matches_identical_and_similar_images(tmp_path) -> None:
    original = tmp_path / "original.png"
    identical = tmp_path / "identical.png"
    similar = tmp_path / "similar.png"
    write_solid_png(original, (220, 30, 30))
    write_solid_png(identical, (220, 30, 30))
    write_solid_png(similar, (225, 35, 35))

    original_hash = inspect_image_asset(original).difference_hash

    assert image_similarity(
        original_hash,
        inspect_image_asset(identical).difference_hash,
    ) == 1.0
    assert image_similarity(
        original_hash,
        inspect_image_asset(similar).difference_hash,
    ) >= 0.97


def test_detect_visible_text_keeps_confident_words_and_filters_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_asset_qa.shutil, "which", lambda _name: "tesseract")
    command = []

    def fake_run(args, **kwargs):
        command.extend(args)
        assert kwargs["timeout"] == 30
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=(
                TSV_HEADER
                + _word_row(88, "Ritzz.Hk")
                + _word_row(20, "uncertain")
                + _word_row(92, "RITZZ.HK")
                + _word_row(90, "A")
            ),
        )

    monkeypatch.setattr(image_asset_qa.subprocess, "run", fake_run)

    assert image_asset_qa.detect_visible_text("scene.png") == ("Ritzz.Hk",)
    assert command == [
        "tesseract",
        "scene.png",
        "stdout",
        "--psm",
        "11",
        "tsv",
    ]


def test_detect_visible_text_fails_explicitly_when_tesseract_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_asset_qa.shutil, "which", lambda _name: None)

    with pytest.raises(FileNotFoundError, match="Tesseract OCR is required"):
        image_asset_qa.detect_visible_text("scene.png")


def test_detect_visible_text_surfaces_tesseract_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(image_asset_qa.shutil, "which", lambda _name: "tesseract")
    monkeypatch.setattr(
        image_asset_qa.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stderr="image decode failed",
            stdout="",
        ),
    )

    with pytest.raises(RuntimeError, match="image decode failed"):
        image_asset_qa.detect_visible_text("scene.png")
