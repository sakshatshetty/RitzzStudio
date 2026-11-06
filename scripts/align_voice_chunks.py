"""Align narration audio chunks to their exact supplied text with WhisperX."""

import argparse
import importlib
import json
from pathlib import Path
from typing import Any


def align_chunks(input_file: Path, output_file: Path) -> None:
    whisperx = importlib.import_module("whisperx")

    payload = json.loads(input_file.read_text(encoding="utf-8"))
    chunks = payload.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("Alignment input must contain at least one audio chunk.")

    device = "cpu"
    model, metadata = whisperx.load_align_model(
        language_code="en",
        device=device,
    )
    aligned_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        audio_file = Path(chunk["audio_file"])
        if not audio_file.is_file():
            raise FileNotFoundError(
                f"Audio chunk for forced alignment was not found: {audio_file}"
            )
        audio = whisperx.load_audio(str(audio_file))
        aligned = whisperx.align(
            [
                {
                    "start": 0.0,
                    "end": float(chunk["duration_seconds"]),
                    "text": chunk["text"],
                }
            ],
            model,
            metadata,
            audio,
            device,
            return_char_alignments=True,
        )
        characters = [
            character
            for segment in aligned["segments"]
            for character in segment.get("chars", [])
        ]
        aligned_chunks.append(
            {
                "characters": characters,
                "text": chunk["text"],
            }
        )

    output_file.write_text(
        json.dumps({"chunks": aligned_chunks}, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    align_chunks(arguments.input, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
