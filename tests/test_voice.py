import pytest
from pydantic import ValidationError

from modules.voice.models import (
    VoiceAlignment,
    VoiceAsset,
    VoiceGenerationRequest,
    VoiceGenerationResult,
)


def test_voice_generation_request():
    request = VoiceGenerationRequest(
        voice_id="test_voice",
        text="This is a Ritzz narration test.",
        output_directory="output/voice",
        output_filename="narration.mp3",
    )

    assert request.voice_id == "test_voice"
    assert request.model_id == "eleven_multilingual_v2"
    assert request.output_format == "mp3_44100_128"
    assert request.voice_settings.stability == 0.72
    assert request.voice_settings.similarity_boost == 0.75
    assert request.voice_settings.style == 0.0
    assert request.voice_settings.use_speaker_boost is True
    assert request.voice_settings.speed == 0.95


def test_voice_generation_request_custom_model():
    request = VoiceGenerationRequest(
        voice_id="test_voice",
        model_id="eleven_v3",
        text="Test narration.",
        output_directory="output/voice",
        output_filename="narration.mp3",
    )

    assert request.model_id == "eleven_v3"


def test_voice_generation_request_adds_final_punctuation():
    request = VoiceGenerationRequest(
        voice_id="test_voice",
        text="A calm explanation without a final stop",
        output_directory="output/voice",
    )
    assert request.text == "A calm explanation without a final stop."


def test_voice_generation_request_validates_minimum_duration():
    request = VoiceGenerationRequest(
        voice_id="test_voice",
        text="A test.",
        output_directory="output/voice",
        minimum_duration_seconds=120,
    )
    assert request.minimum_duration_seconds == 120

    with pytest.raises(ValidationError):
        VoiceGenerationRequest(
            voice_id="test_voice",
            text="A test.",
            output_directory="output/voice",
            minimum_duration_seconds=0,
        )


def test_voice_generation_request_rejects_whitespace_only_text():
    with pytest.raises(ValidationError):
        VoiceGenerationRequest(
            voice_id="test_voice",
            text="   ",
            output_directory="output/voice",
        )


def test_voice_generation_request_requires_text():
    with pytest.raises(ValidationError):
        VoiceGenerationRequest(
            voice_id="test_voice",
            text="",
            output_directory="output/voice",
            output_filename="narration.mp3",
        )


def test_voice_alignment():
    alignment = VoiceAlignment(
        characters=["H", "i"],
        character_start_times_seconds=[
            0.0,
            0.1,
        ],
        character_end_times_seconds=[
            0.1,
            0.2,
        ],
    )

    assert alignment.characters == ["H", "i"]
    assert alignment.character_start_times_seconds == [
        0.0,
        0.1,
    ]
    assert alignment.character_end_times_seconds == [
        0.1,
        0.2,
    ]


def test_voice_asset():
    asset = VoiceAsset(
        voice_id="test_voice",
        model_id="eleven_multilingual_v2",
        status="completed",
        file_path="output/voice/narration.mp3",
        duration_seconds=480.2,
        character_count=5200,
    )

    assert asset.status == "completed"
    assert asset.file_path == (
        "output/voice/narration.mp3"
    )
    assert asset.duration_seconds == 480.2
    assert asset.character_count == 5200


def test_voice_generation_result_failed():
    result = VoiceGenerationResult(
        voice_id="test_voice",
        model_id="eleven_multilingual_v2",
        status="failed",
        error_message="Voice generation failed.",
    )

    assert result.status == "failed"
    assert result.error_message == (
        "Voice generation failed."
    )


def test_invalid_model_fails():
    with pytest.raises(ValidationError):
        VoiceGenerationRequest.model_validate(
            {
                "voice_id": "test_voice",
                "model_id": "invalid_model",
                "text": "Test narration.",
                "output_directory": "output/voice",
                "output_filename": "narration.mp3",
            }
        )


def test_invalid_status_fails():
    with pytest.raises(ValidationError):
        VoiceAsset.model_validate(
            {
                "voice_id": "test_voice",
                "model_id": "eleven_multilingual_v2",
                "status": "invalid",
            }
        )


def test_negative_duration_fails():
    with pytest.raises(ValidationError):
        VoiceAsset.model_validate(
            {
                "voice_id": "test_voice",
                "model_id": "eleven_multilingual_v2",
                "duration_seconds": -1,
            }
        )
