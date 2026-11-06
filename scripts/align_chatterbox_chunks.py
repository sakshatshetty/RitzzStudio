"""Backward-compatible Chatterbox alignment command."""

from pathlib import Path

from scripts import align_voice_chunks


def align_chunks(input_file: Path, output_file: Path) -> None:
    align_voice_chunks.align_chunks(input_file, output_file)


def main() -> int:
    return align_voice_chunks.main()


if __name__ == "__main__":
    raise SystemExit(main())
