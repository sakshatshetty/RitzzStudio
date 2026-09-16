import base64

from modules.voice.elevenlabs import (
    ElevenLabsProvider,
)
from modules.voice.models import (
    VoiceGenerationRequest,
)


class MockResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv(
        "ELEVENLABS_API_KEY",
        raising=False,
    )

    try:
        ElevenLabsProvider()
        assert False
    except ValueError as exc:
        assert "ELEVENLABS_API_KEY" in str(exc)


def test_provider_accepts_api_key():
    provider = ElevenLabsProvider(
        api_key="test-key"
    )

    assert provider.api_key == "test-key"


def test_parse_alignment():
    alignment = (
        ElevenLabsProvider._parse_alignment(
            {
                "characters": ["H", "i"],
                "character_start_times_seconds": [
                    0.0,
                    0.1,
                ],
                "character_end_times_seconds": [
                    0.1,
                    0.2,
                ],
            }
        )
    )

    assert alignment is not None
    assert alignment.characters == [
        "H",
        "i",
    ]

    assert (
        alignment.character_start_times_seconds
        == [0.0, 0.1]
    )

    assert (
        alignment.character_end_times_seconds
        == [0.1, 0.2]
    )


def test_parse_empty_alignment():
    result = ElevenLabsProvider._parse_alignment(
        None
    )

    assert result is None


def test_estimate_duration():
    from modules.voice.models import (
        VoiceAlignment,
    )

    alignment = VoiceAlignment(
        characters=["A", "B"],
        character_start_times_seconds=[
            0.0,
            0.5,
        ],
        character_end_times_seconds=[
            0.5,
            1.0,
        ],
    )

    duration = (
        ElevenLabsProvider._estimate_duration(
            alignment
        )
    )

    assert duration == 1.0


def test_generate_with_mocked_request(
    monkeypatch,
    tmp_path,
):
    audio = b"fake-mp3-audio"

    response_data = {
        "audio_base64": base64.b64encode(
            audio
        ).decode("utf-8"),
        "alignment": {
            "characters": ["H", "i"],
            "character_start_times_seconds": [
                0.0,
                0.1,
            ],
            "character_end_times_seconds": [
                0.1,
                0.2,
            ],
        },
    }

    def mock_post(
        url,
        headers,
        json,
        timeout,
    ):
        assert (
            "test-voice"
            in url
        )

        assert headers[
            "xi-api-key"
        ] == "test-key"

        assert json["text"] == "Hello"
        assert (
            json["model_id"]
            == "eleven_multilingual_v2"
        )

        return MockResponse(
            response_data
        )

    monkeypatch.setattr(
        "modules.voice.elevenlabs.requests.post",
        mock_post,
    )

    provider = ElevenLabsProvider(
        api_key="test-key"
    )

    request = VoiceGenerationRequest(
        voice_id="test-voice",
        text="Hello",
        output_directory=str(
            tmp_path
        ),
        output_filename="narration.mp3",
    )

    result = provider.generate(
        request
    )

    assert result.status == "completed"

    assert result.file_path is not None

    assert (
        result.duration_seconds
        == 0.2
    )

    assert (
        result.character_count
        == 5
    )

    assert (
        result.alignment is not None
    )

    output_file = (
        tmp_path / "narration.mp3"
    )

    assert output_file.exists()

    assert (
        output_file.read_bytes()
        == audio
    )


def test_generate_failure_is_returned(
    monkeypatch,
    tmp_path,
):
    def mock_post(
        url,
        headers,
        json,
        timeout,
    ):
        raise RuntimeError(
            "API unavailable"
        )

    monkeypatch.setattr(
        "modules.voice.elevenlabs.requests.post",
        mock_post,
    )

    provider = ElevenLabsProvider(
        api_key="test-key"
    )

    request = VoiceGenerationRequest(
        voice_id="test-voice",
        text="Hello",
        output_directory=str(
            tmp_path
        ),
        output_filename="narration.mp3",
    )

    result = provider.generate(
        request
    )

    assert result.status == "failed"

    assert (
        result.error_message
        == "API unavailable"
    )