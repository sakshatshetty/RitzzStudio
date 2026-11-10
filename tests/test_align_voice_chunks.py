import json
import sys
from types import ModuleType

from scripts.align_voice_chunks import align_chunks


def test_align_chunks_loads_model_once_and_reports_per_chunk_progress(
    tmp_path,
    monkeypatch,
    capsys,
):
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.json"
    audio_files = [tmp_path / "part-0000.wav", tmp_path / "part-0001.wav"]
    for audio_file in audio_files:
        audio_file.write_bytes(b"fake audio")
    chunks = [
        {
            "audio_file": str(audio_files[0]),
            "duration_seconds": 1.5,
            "text": "First.",
        },
        {
            "audio_file": str(audio_files[1]),
            "duration_seconds": 2.0,
            "text": "Second.",
        },
    ]
    input_file.write_text(json.dumps({"chunks": chunks}), encoding="utf-8")
    calls = {"align": [], "audio": [], "model": 0}
    whisperx = ModuleType("whisperx")

    def load_align_model(*, language_code, device):
        calls["model"] += 1
        assert language_code == "en"
        assert device == "cpu"
        return "align-model", {"language": language_code}

    def load_audio(path):
        calls["audio"].append(path)
        return f"audio:{path}"

    def align(segments, _model, _metadata, audio, _device, **kwargs):
        calls["align"].append((segments, audio, kwargs))
        return {
            "segments": [
                {
                    "chars": [
                        {"char": character, "start": 0.0, "end": 0.1}
                        for character in segments[0]["text"]
                        if character.isalnum()
                    ]
                }
            ]
        }

    whisperx.load_align_model = load_align_model
    whisperx.load_audio = load_audio
    whisperx.align = align
    monkeypatch.setitem(sys.modules, "whisperx", whisperx)

    align_chunks(input_file, output_file)

    assert calls["model"] == 1
    assert calls["audio"] == [str(path) for path in audio_files]
    assert [call[0][0]["text"] for call in calls["align"]] == [
        "First.",
        "Second.",
    ]
    assert all(call[2]["return_char_alignments"] is True for call in calls["align"])
    result = json.loads(output_file.read_text(encoding="utf-8"))
    assert [chunk["text"] for chunk in result["chunks"]] == [
        "First.",
        "Second.",
    ]
    progress = capsys.readouterr().out
    assert "Aligning chunk 1/2" in progress
    assert "Aligned chunk 2/2." in progress
