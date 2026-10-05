from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImageAssetInspection:
    width: int
    height: int
    color_type: int
    difference_hash: int


def inspect_image_asset(path: str | Path) -> ImageAssetInspection:
    image_path = Path(path)
    if not image_path.is_file() or image_path.stat().st_size == 0:
        raise ValueError("missing or empty image")
    data = image_path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")

    offset = 8
    width = height = bit_depth = color_type = interlace = None
    compressed = bytearray()
    saw_end = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            raise ValueError("truncated PNG chunk")
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[offset + 8 + length:chunk_end])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
            raise ValueError("PNG checksum mismatch")
        if kind == b"IHDR":
            if length != 13:
                raise ValueError("invalid PNG header")
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", payload)
            )
            if compression != 0 or filtering != 0:
                raise ValueError("unsupported PNG compression or filtering")
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            saw_end = True
            break
        offset = chunk_end

    if not saw_end or width is None or height is None or not compressed:
        raise ValueError("incomplete PNG image")
    if width < 1 or height < 1:
        raise ValueError("invalid image dimensions")
    if bit_depth != 8 or color_type not in {2, 6} or interlace != 0:
        raise ValueError(
            "unsupported image color mode; expected non-interlaced 8-bit RGB or RGBA"
        )

    channels = 3 if color_type == 2 else 4
    stride = width * channels
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as exc:
        raise ValueError("invalid PNG image data") from exc
    if len(raw) != height * (stride + 1):
        raise ValueError("PNG pixel data does not match its dimensions")

    rows: list[bytearray] = []
    previous = bytearray(stride)
    raw_offset = 0
    for _ in range(height):
        filter_type = raw[raw_offset]
        raw_offset += 1
        scanline = bytearray(raw[raw_offset:raw_offset + stride])
        raw_offset += stride
        if filter_type == 1:
            for i in range(channels, stride):
                scanline[i] = (scanline[i] + scanline[i - channels]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                scanline[i] = (scanline[i] + previous[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = scanline[i - channels] if i >= channels else 0
                scanline[i] = (scanline[i] + ((left + previous[i]) // 2)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = scanline[i - channels] if i >= channels else 0
                above = previous[i]
                upper_left = previous[i - channels] if i >= channels else 0
                predictor = left + above - upper_left
                distances = (
                    abs(predictor - left),
                    abs(predictor - above),
                    abs(predictor - upper_left),
                )
                nearest = distances.index(min(distances))
                paeth = (left, above, upper_left)[nearest]
                scanline[i] = (scanline[i] + paeth) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"unsupported PNG row filter: {filter_type}")
        rows.append(scanline)
        previous = scanline

    samples: list[int] = []
    color_bits = 0
    for y in range(8):
        source_y = min(height - 1, ((2 * y + 1) * height) // 16)
        row = rows[source_y]
        color_samples: list[tuple[int, int, int]] = []
        for x in range(9):
            source_x = min(width - 1, ((2 * x + 1) * width) // 18)
            start = source_x * channels
            red, green, blue = row[start:start + 3]
            samples.append((299 * red + 587 * green + 114 * blue) // 1000)
            if x < 8:
                color_samples.append((red, green, blue))
        for red, green, blue in color_samples:
            color_bits = (color_bits << 6) | (
                (red >> 6) << 4
                | (green >> 6) << 2
                | (blue >> 6)
            )

    difference_hash = 0
    bit = 0
    for y in range(8):
        for x in range(8):
            if samples[y * 9 + x] > samples[y * 9 + x + 1]:
                difference_hash |= 1 << bit
            bit += 1
    perceptual_hash = (difference_hash << 384) | color_bits
    return ImageAssetInspection(width, height, color_type, perceptual_hash)


def expected_image_size() -> tuple[int, int]:
    try:
        width = int(os.getenv("RITZZ_QA_IMAGE_WIDTH", "1536"))
        height = int(os.getenv("RITZZ_QA_IMAGE_HEIGHT", "864"))
    except ValueError as exc:
        raise ValueError("RITZZ_QA_IMAGE_WIDTH and HEIGHT must be positive integers.") from exc
    if width <= 0 or height <= 0:
        raise ValueError("RITZZ_QA_IMAGE_WIDTH and HEIGHT must be positive integers.")
    return width, height


def image_similarity(left: int, right: int) -> float:
    distance = (left ^ right).bit_count()
    return 1.0 - distance / 448


def duplicate_scene_findings(
    scene_ids: list[str],
    hashes: list[int | None],
    *,
    threshold: float,
    window: int,
) -> dict[int, str]:
    if len(scene_ids) != len(hashes):
        raise ValueError("Scene IDs and image hashes must have equal lengths.")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("Image similarity threshold must be between 0 and 1.")
    if window < 1:
        raise ValueError("Image duplicate window must be at least one.")

    findings: dict[int, str] = {}
    for index, current_hash in enumerate(hashes):
        if current_hash is None:
            continue
        for previous_index in range(max(0, index - window), index):
            previous_hash = hashes[previous_index]
            if previous_hash is None:
                continue
            similarity = image_similarity(current_hash, previous_hash)
            if similarity >= threshold:
                findings[index] = (
                    f"{scene_ids[index]} is perceptually similar to "
                    f"{scene_ids[previous_index]} ({similarity:.1%}; "
                    f"threshold {threshold:.1%}). Create a substantially "
                    "different composition, action, character placement, and background."
                )
                break
    return findings
