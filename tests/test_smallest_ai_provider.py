from pathlib import Path

import pytest

from modules.voice.models import VoiceAlignment, VoiceGenerationRequest
from modules.voice.smallest_ai import SmallestAIProvider

_WAV_RESPONSE = (
    b"RIFF"
    + b"\x24\x00\x00\x00"
    + b"WAVE"
    + b"fmt "
    + b"\x10\x00\x00\x00"
    + b"\x01\x00\x01\x00"
    + b"\x80\x3e\x00\x00"
    + b"\x00\x7d\x00\x00"
    + b"\x02\x00\x10\x00"
    + b"data"
    + b"\x00\x00\x00\x00"
)


class _FakeResponse:
    def __init__(self, content: bytes = _WAV_RESPONSE) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


def _request(
    tmp_path: Path,
    text: str = "Hello there.",
    voice_id: str = "meher",
) -> VoiceGenerationRequest:
    return VoiceGenerationRequest(
        voice_id=voice_id,
        model_id="lightning_v3.1_pro",
        text=text,
        output_directory=str(tmp_path),
        preserve_text=True,
    )


def _mock_local_audio_steps(monkeypatch, provider, text: str) -> None:
    alignment = VoiceAlignment(
        characters=list(text),
        character_start_times_seconds=[0.0] * len(text),
        character_end_times_seconds=[0.2] * len(text),
    )
    monkeypatch.setattr(provider, "_align_audio", lambda *_args: alignment)
    monkeypatch.setattr(
        "modules.voice.smallest_ai.probe_audio_duration",
        lambda _path: 3.5,
    )

    def fake_ffmpeg(command, *, cwd, check):
        assert check is True
        assert Path(cwd).is_dir()
        Path(command[-1]).write_bytes(b"fake-mp3")

    monkeypatch.setattr(
        "modules.voice.smallest_ai.subprocess.run",
        fake_ffmpeg,
    )


def test_smallest_provider_synthesizes_wav_and_aligns(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SMALLEST_API_KEY", "test-api-key")
    provider = SmallestAIProvider()
    requests = []

    def fake_post(url, *, headers, json, timeout):
        requests.append({
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        })
        return _FakeResponse()

    monkeypatch.setattr("modules.voice.smallest_ai.requests.post", fake_post)
    _mock_local_audio_steps(monkeypatch, provider, "Hello there.")

    result = provider.generate(_request(tmp_path))

    assert result.status == "completed"
    assert result.model_id == "lightning_v3.1_pro"
    assert result.voice_id == "meher"
    assert result.duration_seconds == 3.5
    assert result.file_path is not None
    assert Path(result.file_path).read_bytes() == b"fake-mp3"
    assert len(requests) == 1
    api_request = requests[0]
    assert api_request["url"] == "https://api.smallest.ai/waves/v1/tts"
    assert api_request["headers"] == {
        "Authorization": "Bearer test-api-key",
        "Content-Type": "application/json",
        "Accept": "audio/wav",
    }
    assert api_request["json"] == {
        "text": "Hello there.",
        "voice_id": "meher",
        "model": "lightning_v3.1_pro",
        "sample_rate": 24000,
        "speed": 0.92,
        "language": "en",
        "output_format": "wav",
    }


def test_smallest_provider_splits_long_text_into_recommended_chunks(
    tmp_path,
    monkeypatch,
):
    text = "A complete sentence for narration. " * 18
    monkeypatch.setenv("SMALLEST_API_KEY", "test-api-key")
    provider = SmallestAIProvider()
    requested_text: list[str] = []
    monkeypatch.setattr(
        "modules.voice.smallest_ai.requests.post",
        lambda _url, *, json, **_kwargs: (
            requested_text.append(json["text"]) or _FakeResponse()
        ),
    )
    _mock_local_audio_steps(monkeypatch, provider, text)

    result = provider.generate(_request(tmp_path, text=text))

    assert result.status == "completed"
    assert len(requested_text) > 1
    assert "".join(requested_text) == text
    assert all(
        len(chunk) <= SmallestAIProvider.MAX_INPUT_CHARACTERS
        for chunk in requested_text
    )


def test_text_chunking_handles_long_tokens_and_preserves_input():
    text = "x" * (SmallestAIProvider.MAX_INPUT_CHARACTERS + 20)

    chunks = SmallestAIProvider._split_text(text)

    assert "".join(chunks) == text
    assert all(
        len(chunk) <= SmallestAIProvider.MAX_INPUT_CHARACTERS
        for chunk in chunks
    )


def test_smallest_provider_rejects_non_wav_response(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("SMALLEST_API_KEY", "test-api-key")
    provider = SmallestAIProvider()
    monkeypatch.setattr(
        "modules.voice.smallest_ai.requests.post",
        lambda *_args, **_kwargs: _FakeResponse(b"not audio"),
    )

    with pytest.raises(ValueError, match="valid WAV"):
        provider.generate(_request(tmp_path))


def test_smallest_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("SMALLEST_API_KEY", raising=False)

    with pytest.raises(ValueError, match="SMALLEST_API_KEY"):
        SmallestAIProvider()


def test_smallest_provider_rejects_unsupported_model(tmp_path, monkeypatch):
    monkeypatch.setenv("SMALLEST_API_KEY", "test-api-key")
    provider = SmallestAIProvider()
    request = _request(tmp_path).model_copy(update={"model_id": "eleven_v4_turbo"})

    with pytest.raises(ValueError, match="supports only"):
        provider.generate(request)
