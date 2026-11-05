import math
from itertools import pairwise
from typing import Any

from modules.voice.models import VoiceAlignment


def build_alignment(
    text: str,
    input_chunks: list[dict[str, Any]],
    aligned_chunks: list[dict[str, Any]],
    duration_seconds: float,
) -> VoiceAlignment:
    if len(input_chunks) != len(aligned_chunks):
        raise ValueError("WhisperX did not return alignment for every audio chunk.")

    starts: list[float | None] = [None] * len(text)
    ends: list[float | None] = [None] * len(text)
    for input_chunk, aligned_chunk in zip(
        input_chunks,
        aligned_chunks,
        strict=True,
    ):
        start_index = input_chunk["start_character"]
        end_index = input_chunk["end_character"]
        chunk_text = input_chunk["text"]
        if text[start_index:end_index] != chunk_text:
            raise ValueError("Narration chunk boundaries do not match the script.")
        if aligned_chunk.get("text") != chunk_text:
            raise ValueError(
                "WhisperX alignment text does not match the generated audio text."
            )

        chunk_starts, chunk_ends = align_chunk_characters(
            chunk_text,
            aligned_chunk.get("characters", []),
            input_chunk["audio_offset_seconds"],
            input_chunk["duration_seconds"],
        )
        starts[start_index:end_index] = chunk_starts
        ends[start_index:end_index] = chunk_ends

    for index, character in enumerate(text):
        if starts[index] is None:
            if character.isalnum():
                raise ValueError(
                    f"WhisperX did not align narration character at index {index}."
                )
            previous_end = next(
                (ends[position] for position in range(index - 1, -1, -1)
                 if ends[position] is not None),
                None,
            )
            next_start = next(
                (starts[position] for position in range(index + 1, len(text))
                 if starts[position] is not None),
                None,
            )
            timestamp = (
                previous_end
                if previous_end is not None
                else next_start
                if next_start is not None
                else duration_seconds
            )
            starts[index] = timestamp
            ends[index] = timestamp

    final_starts = [float(value) for value in starts if value is not None]
    final_ends = [float(value) for value in ends if value is not None]
    if len(final_starts) != len(text) or len(final_ends) != len(text):
        raise ValueError("WhisperX alignment does not cover the supplied narration.")
    if any(
        not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end < start
        or end > duration_seconds + 0.25
        for start, end in zip(final_starts, final_ends, strict=True)
    ):
        raise ValueError("WhisperX returned invalid narration timestamps.")
    if any(
        current < previous
        for previous, current in pairwise(final_starts)
    ) or any(
        current < previous
        for previous, current in pairwise(final_ends)
    ):
        raise ValueError("WhisperX returned non-monotonic narration timestamps.")
    return VoiceAlignment(
        characters=list(text),
        character_start_times_seconds=final_starts,
        character_end_times_seconds=final_ends,
    )


def align_chunk_characters(
    text: str,
    aligned_characters: list[dict[str, Any]],
    audio_offset_seconds: float,
    chunk_duration_seconds: float,
) -> tuple[list[float], list[float]]:
    aligned_letters = [
        item for item in aligned_characters
        if str(item.get("char", "")).isalnum()
    ]
    expected_letters = [character for character in text if character.isalnum()]
    aligned_text = "".join(str(item["char"]) for item in aligned_letters)
    expected_text = "".join(expected_letters)
    if aligned_text.casefold() != expected_text.casefold():
        raise ValueError(
            "WhisperX did not align every spoken letter and digit in a narration chunk."
        )

    mapped: dict[int, tuple[float, float]] = {}
    letter_index = 0
    for index, character in enumerate(text):
        if not character.isalnum():
            continue
        item = aligned_letters[letter_index]
        letter_index += 1
        start = item.get("start")
        end = item.get("end")
        if start is None or end is None:
            raise ValueError(
                f"WhisperX returned no timestamp for narration character at index {index}."
            )
        start = float(start)
        end = float(end)
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < start
            or end > chunk_duration_seconds + 0.25
        ):
            raise ValueError(
                f"WhisperX returned invalid timestamps for narration character at index {index}."
            )
        mapped[index] = (
            audio_offset_seconds + start,
            audio_offset_seconds + end,
        )

    starts: list[float] = []
    ends: list[float] = []
    for index, character in enumerate(text):
        if index in mapped:
            start, end = mapped[index]
        else:
            previous_end = next(
                (mapped[position][1] for position in range(index - 1, -1, -1)
                 if position in mapped),
                None,
            )
            next_start = next(
                (mapped[position][0] for position in range(index + 1, len(text))
                 if position in mapped),
                None,
            )
            timestamp = (
                previous_end
                if previous_end is not None
                else next_start
                if next_start is not None
                else audio_offset_seconds
            )
            start = end = timestamp
        starts.append(start)
        ends.append(end)
    return starts, ends
