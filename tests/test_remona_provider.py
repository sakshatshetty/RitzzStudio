from pathlib import Path

import pytest

from modules.voice.models import VoiceAlignment, VoiceGenerationRequest
from modules.voice.remona import RemonaProvider


class _Response:
    def __init__(self, *, data=None, content=b""):
        self._data = data
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _request(tmp_path: Path) -> VoiceGenerationRequest:
    return VoiceGenerationRequest(
        voice_id="remona-preset:Maya",
        model_id="eleven_multilingual_v2",
        text="Hello there.",
        output_directory=str(tmp_path),
    )


def test_remona_submits_once_polls_downloads_and_aligns(
    tmp_path,
    monkeypatch,
):
    provider = RemonaProvider(
        api_key="test-key",
        voice_preset="Maya",
    )
    post_calls = []
    get_calls = []
    task_states = iter(
        [
            {"status": "running"},
            {
                "status": "completed",
                "output": ["https://audio.example/narration.wav"],
            },
        ]
    )

    def fake_post(url, *, headers, json, timeout):
        post_calls.append((url, headers, json, timeout))
        return _Response(data={"id": "task-123", "estimatedCost": {"credits": 1}})

    def fake_get(url, *, headers=None, timeout):
        get_calls.append((url, headers, timeout))
        if url.endswith("/tasks/task-123"):
            return _Response(data=next(task_states))
        return _Response(content=b"source audio")

    def fake_ffmpeg(command, *, check):
        assert check is True
        Path(command[-1]).write_bytes(b"encoded mp3")

    alignment = VoiceAlignment(
        characters=list("Hello there."),
        character_start_times_seconds=[0.0] * 12,
        character_end_times_seconds=[0.2] * 12,
    )
    monkeypatch.setattr("modules.voice.remona.requests.post", fake_post)
    monkeypatch.setattr("modules.voice.remona.requests.get", fake_get)
    monkeypatch.setattr("modules.voice.remona.subprocess.run", fake_ffmpeg)
    monkeypatch.setattr("modules.voice.remona.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "modules.voice.remona.probe_audio_duration",
        lambda _path: 1.5,
    )
    monkeypatch.setattr(
        provider,
        "_align_audio",
        lambda audio_file, text, duration, temporary_path: alignment,
    )

    result = provider.generate(_request(tmp_path))

    assert len(post_calls) == 1
    request_url, headers, payload, _timeout = post_calls[0]
    assert request_url == "https://remona.net/runwayml/v1/text_to_speech"
    assert headers["Authorization"] == "Bearer test-key"
    assert payload == {
        "model": "eleven_multilingual_v2",
        "promptText": "Hello there.",
        "voice": {"type": "runway-preset", "presetId": "Maya"},
    }
    assert [call[0] for call in get_calls] == [
        "https://remona.net/runwayml/v1/tasks/task-123",
        "https://remona.net/runwayml/v1/tasks/task-123",
        "https://audio.example/narration.wav",
    ]
    assert result.status == "completed"
    assert result.voice_id == "remona-preset:Maya"
    assert result.model_id == "eleven_multilingual_v2"
    assert result.duration_seconds == 1.5
    assert result.alignment == alignment
    assert Path(result.file_path).read_bytes() == b"encoded mp3"


def test_remona_rejects_missing_api_key_or_preset():
    with pytest.raises(ValueError, match="REMONA_API_KEY"):
        RemonaProvider(api_key="", voice_preset="Maya")

    with pytest.raises(ValueError, match="REMONA_VOICE_PRESET"):
        RemonaProvider(api_key="test-key", voice_preset="")


def test_remona_rejects_task_without_id(monkeypatch, tmp_path):
    provider = RemonaProvider(api_key="test-key", voice_preset="Maya")
    monkeypatch.setattr(
        "modules.voice.remona.requests.post",
        lambda *args, **kwargs: _Response(data={"estimatedCost": {"credits": 1}}),
    )

    with pytest.raises(ValueError, match="did not return an id"):
        provider.generate(_request(tmp_path))


def test_remona_reports_failed_task_without_downloading_audio(
    monkeypatch,
):
    provider = RemonaProvider(api_key="test-key", voice_preset="Maya")
    monkeypatch.setattr(
        "modules.voice.remona.requests.post",
        lambda *args, **kwargs: _Response(data={"id": "task-123"}),
    )
    monkeypatch.setattr(
        "modules.voice.remona.requests.get",
        lambda *args, **kwargs: _Response(
            data={"status": "failed", "error": "upstream synthesis failed"}
        ),
    )

    with pytest.raises(RuntimeError, match="upstream synthesis failed"):
        provider._wait_for_audio_url("task-123", {"Authorization": "Bearer test-key"})


def test_remona_output_url_must_be_https():
    assert RemonaProvider._find_audio_url(
        {"audio": "http://audio.example/narration.wav"}
    ) is None
    assert RemonaProvider._find_audio_url(
        {"outputs": [{"url": "https://audio.example/narration.wav"}]}
    ) == "https://audio.example/narration.wav"
