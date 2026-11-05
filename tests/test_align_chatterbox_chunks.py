import json
import sys
from types import ModuleType

from scripts.align_chatterbox_chunks import align_chunks


def test_align_chunks_requests_character_timestamps_and_writes_results(
    tmp_path,
    monkeypatch,
):
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.json"
    audio_file = tmp_path / "chunk.wav"
    audio_file.write_bytes(b"fake audio")
    input_file.write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "audio_file": str(audio_file),
                        "duration_seconds": 1.5,
                        "text": "A test.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calls = {}
    whisperx = ModuleType("whisperx")

    def load_align_model(*, language_code, device):
        calls["model"] = (language_code, device)
        return "align-model", {"language": language_code}

    def load_audio(path):
        calls["audio"] = path
        return "waveform"

    def align(*args, **kwargs):
        calls["align"] = (args, kwargs)
        return {
            "segments": [
                {
                    "chars": [
                        {"char": "A", "start": 0.1, "end": 0.2},
                        {"char": "t", "start": 0.3, "end": 0.4},
                    ]
                }
            ]
        }

    whisperx.load_align_model = load_align_model
    whisperx.load_audio = load_audio
    whisperx.align = align
    monkeypatch.setitem(sys.modules, "whisperx", whisperx)

    align_chunks(input_file, output_file)

    arguments, keyword_arguments = calls["align"]
    assert arguments[0][0]["text"] == "A test."
    assert keyword_arguments["return_char_alignments"] is True
    assert calls["model"] == ("en", "cpu")
    result = json.loads(output_file.read_text(encoding="utf-8"))
    assert result["chunks"][0]["text"] == "A test."
    assert result["chunks"][0]["characters"][1]["char"] == "t"
