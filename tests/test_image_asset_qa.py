import struct
import zlib

from modules.video.image_asset_qa import image_similarity, inspect_image_asset


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
