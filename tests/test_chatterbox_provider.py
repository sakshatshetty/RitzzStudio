import json
import sys
from itertools import pairwise
from pathlib import Path
from types import ModuleType

import pytest

from modules.voice.chatterbox import ChatterboxTurboProvider
from modules.voice.models import VoiceGenerationRequest


def _install_fake_audio_dependencies(monkeypatch):
    numpy = ModuleType("numpy")
    numpy_float32 = object()

    class _FakeArray:
        def __init__(self, values, dtype=None):
            self.values = list(values)
            self.dtype = dtype

        def squeeze(self):
            return self

        @property
        def ndim(self):
            return 1

        @property
        def size(self):
            return len(self.values)

    class _FiniteValues:
        @staticmethod
        def all():
            return True

    def asarray(values, dtype=None):
        return _FakeArray(values, dtype)

    def concatenate(arrays):
        return _FakeArray(
            [value for array in arrays for value in array.values],
            arrays[0].dtype,
        )

    numpy.__dict__["float32"] = numpy_float32
    numpy.__dict__["asarray"] = asarray
    numpy.__dict__["concatenate"] = concatenate
    def isfinite(values):
        assert isinstance(values, _FakeArray)
        return _FiniteValues()

    numpy.__dict__["zeros"] = lambda size, dtype=None: _FakeArray(
        [0.0] * size,
        dtype,
    )
    numpy.__dict__["isfinite"] = isfinite
    soundfile = ModuleType("soundfile")

    def write(path, audio, sample_rate, *, subtype):
        assert isinstance(audio, _FakeArray)
        assert sample_rate == 1000
        assert subtype == "PCM_16"
        Path(path).write_bytes(b"wav audio")

    soundfile.__dict__["write"] = write
    monkeypatch.setitem(sys.modules, "numpy", numpy)
    monkeypatch.setitem(sys.modules, "soundfile", soundfile)
    return numpy_float32


def test_install_float32_resampler_normalizes_resampled_audio(monkeypatch):
    numpy_float32 = _install_fake_audio_dependencies(monkeypatch)
    librosa = ModuleType("test_librosa")

    def original_resample(audio, *, orig_sr, target_sr):
        assert audio == [0.1]
        assert orig_sr == 24000
        assert target_sr == 16000
        return [0.1]

    librosa.__dict__["resample"] = original_resample
    chatterbox_turbo = ModuleType("test_chatterbox_turbo")
    chatterbox_turbo.__dict__["librosa"] = librosa

    ChatterboxTurboProvider._install_float32_resampling(chatterbox_turbo)
    wrapped_resample = librosa.resample
    result = librosa.resample([0.1], orig_sr=24000, target_sr=16000)
    ChatterboxTurboProvider._install_float32_resampling(chatterbox_turbo)

    assert result.dtype is numpy_float32
    assert librosa.resample is wrapped_resample


def test_turbo_model_label_is_set_without_constructor_keyword():
    class _LegacyTurbo:
        def __init__(
            self,
            t3,
            s3gen,
            ve,
            tokenizer,
            device,
            conds=None,
        ):
            self.conds = conds

    conditionals = object()
    model = ChatterboxTurboProvider._construct_turbo_model(
        _LegacyTurbo,
        object(),
        object(),
        object(),
        object(),
        "cpu",
        conditionals,
        "Turbo",
    )

    assert model.conds is conditionals
    assert model.model_label == "Turbo"


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
    _install_fake_audio_dependencies(monkeypatch)

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


def test_generate_loads_saved_conditionals_without_reference_audio(
    tmp_path,
    monkeypatch,
):
    _install_fake_audio_dependencies(monkeypatch)

    profile_file = tmp_path / "voice-conditionals.pt"
    profile_file.write_bytes(b"saved conditionals")
    loaded_conditionals = object()
    load_calls = []

    class _FakeConditionals:
        @classmethod
        def load(cls, path, *, map_location):
            load_calls.append((Path(path), map_location))
            return cls()

        def to(self, device):
            assert device == "cpu"
            return loaded_conditionals

    fake_package = ModuleType("chatterbox")
    fake_package.__path__ = []
    fake_turbo = ModuleType("chatterbox.tts_turbo")
    fake_turbo.__dict__["Conditionals"] = _FakeConditionals
    fake_package.__dict__["tts_turbo"] = fake_turbo
    monkeypatch.setitem(sys.modules, "chatterbox", fake_package)
    monkeypatch.setitem(sys.modules, "chatterbox.tts_turbo", fake_turbo)

    class _FakeModel:
        sr = 1000
        device = "cpu"
        conds = None

        def generate(self, text):
            assert text == "One."
            assert self.conds is loaded_conditionals
            return [0.1] * 1000

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
    provider = ChatterboxTurboProvider(
        conditionals_path=profile_file,
        model=_FakeModel(),
    )
    request = VoiceGenerationRequest(
        voice_id="chatterbox:saved-profile",
        model_id="chatterbox_turbo",
        preserve_text=True,
        text="One.",
        output_directory=str(tmp_path / "voice"),
    )

    result = provider.generate(request)

    assert result.status == "completed"
    assert load_calls == [(profile_file.resolve(), "cpu")]
    assert len(commands) == 2
