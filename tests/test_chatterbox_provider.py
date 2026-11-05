import json
from itertools import pairwise
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from modules.voice.chatterbox import ChatterboxTurboProvider
from modules.voice.models import VoiceGenerationRequest


def test_install_float32_resampler_normalizes_resampled_audio():
    librosa = ModuleType("test_librosa")
    def original_resample(audio, *, orig_sr, target_sr):
        assert audio == [0.1]
        assert orig_sr == 24000
        assert target_sr == 16000
        return np.array([0.1], dtype=np.float64)

    librosa.__dict__["resample"] = original_resample
    chatterbox_turbo = ModuleType("test_chatterbox_turbo")
    chatterbox_turbo.__dict__["librosa"] = librosa

    ChatterboxTurboProvider._install_float32_resampling(chatterbox_turbo)
    wrapped_resample = librosa.resample
    result = librosa.resample([0.1], orig_sr=24000, target_sr=16000)
    ChatterboxTurboProvider._install_float32_resampling(chatterbox_turbo)

    assert result.dtype == np.float32
    assert librosa.resample is wrapped_resample


def _aligned_characters(text: str) -> list[dict[str, float | str]]:
    result = []
    timestamp = 0.0
    for character in text:
        if character.isalnum():
            result.append(
                {
                    "char": character,
                    "start": timestamp,
                    "end": timestamp + 0.1,
                }
            )
            timestamp += 0.1
    return result


def test_text_chunks_keep_original_offsets_and_text():
    text = "First sentence.  Second sentence.\n\nThird sentence."

    chunks = ChatterboxTurboProvider._text_chunks(text)

    assert len(chunks) == 1
    start, end, chunk_text = chunks[0]
    assert (start, end) == (0, len(text))
    assert chunk_text == text


def test_long_text_chunks_only_at_word_boundaries():
    text = " ".join(f"word{index}" for index in range(100))

    chunks = ChatterboxTurboProvider._text_chunks(text)

    assert len(chunks) > 1
    assert all(len(chunk_text) <= 320 for _, _, chunk_text in chunks)
    assert all(text[start:end] == chunk_text for start, end, chunk_text in chunks)
    assert all(
        text[end].isspace()
        for (_, end, _), (start, _, _) in pairwise(chunks)
        if end < start
    )


def test_character_alignment_restores_unaligned_punctuation():
    text = "Hi, 42!"

    starts, ends = ChatterboxTurboProvider._align_chunk_characters(
        text,
        _aligned_characters(text),
        audio_offset_seconds=2.0,
        chunk_duration_seconds=1.0,
    )

    assert len(starts) == len(text)
    assert len(ends) == len(text)
    assert starts[0] == 2.0
    assert starts[2] == ends[1]
    assert starts[3] == ends[1]
    assert starts[-1] == ends[-2]
    assert all(left <= right for left, right in pairwise(starts))
    assert all(left <= right for left, right in pairwise(ends))


def test_character_alignment_fails_if_a_spoken_digit_is_not_aligned():
    with pytest.raises(ValueError, match="every spoken letter and digit"):
        ChatterboxTurboProvider._align_chunk_characters(
            "Room 42",
            _aligned_characters("Room"),
            audio_offset_seconds=0.0,
            chunk_duration_seconds=1.0,
        )


def test_build_alignment_fills_only_nonspoken_separator_characters():
    text = "One. Two."
    input_chunks = [
        {
            "audio_offset_seconds": 0.0,
            "duration_seconds": 1.0,
            "end_character": 4,
            "start_character": 0,
            "text": "One.",
        },
        {
            "audio_offset_seconds": 1.12,
            "duration_seconds": 1.0,
            "end_character": len(text),
            "start_character": 5,
            "text": "Two.",
        },
    ]
    aligned_chunks = [
        {"characters": _aligned_characters("One."), "text": "One."},
        {"characters": _aligned_characters("Two."), "text": "Two."},
    ]

    alignment = ChatterboxTurboProvider._build_alignment(
        text,
        input_chunks,
        aligned_chunks,
        duration_seconds=2.12,
    )

    assert "".join(alignment.characters) == text
    assert len(alignment.character_start_times_seconds) == len(text)
    assert all(
        first <= second
        for first, second in pairwise(alignment.character_start_times_seconds)
    )
    assert all(
        first <= second
        for first, second in pairwise(alignment.character_end_times_seconds)
    )


def test_build_alignment_rejects_mismatched_script_text():
    with pytest.raises(ValueError, match="boundaries do not match"):
        ChatterboxTurboProvider._build_alignment(
            "Changed.",
            [
                {
                    "audio_offset_seconds": 0.0,
                    "duration_seconds": 1.0,
                    "end_character": 4,
                    "start_character": 0,
                    "text": "One.",
                }
            ],
            [{"characters": _aligned_characters("One."), "text": "One."}],
            duration_seconds=1.0,
        )


def test_generate_synthesizes_aligns_and_encodes_audio(tmp_path, monkeypatch):
    class _FakeModel:
        sr = 1000

        @staticmethod
        def generate(text, *, audio_prompt_path):
            assert text == "One."
            assert Path(audio_prompt_path).is_file()
            return [0.1] * 1000

    reference_file = tmp_path / "reference.wav"
    reference_file.write_bytes(b"private reference")
    commands = []

    def fake_run(command, check):
        assert check is True
        commands.append(command)
        if command[1].endswith("align_chatterbox_chunks.py"):
            input_file = Path(command[3])
            output_file = Path(command[5])
            payload = json.loads(input_file.read_text(encoding="utf-8"))
            output_file.write_text(
                json.dumps(
                    {
                        "chunks": [
                            {
                                "characters": _aligned_characters(
                                    chunk["text"]
                                ),
                                "text": chunk["text"],
                            }
                            for chunk in payload["chunks"]
                        ]
                    }
                ),
                encoding="utf-8",
            )
        else:
            Path(command[-1]).write_bytes(b"encoded mp3")

    monkeypatch.setattr(
        "modules.voice.chatterbox.subprocess.run",
        fake_run,
    )
    provider = ChatterboxTurboProvider(reference_file, model=_FakeModel())
    request = VoiceGenerationRequest(
        voice_id="chatterbox:reference",
        model_id="chatterbox_turbo",
        preserve_text=True,
        text="One.",
        output_directory=str(tmp_path / "voice"),
    )

    result = provider.generate(request)

    assert result.status == "completed"
    assert result.model_id == "chatterbox_turbo"
    assert result.file_path is not None
    assert Path(result.file_path).read_bytes() == b"encoded mp3"
    assert result.alignment is not None
    assert "".join(result.alignment.characters) == "One."
    assert len(commands) == 2
