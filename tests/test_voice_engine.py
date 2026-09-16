from pathlib import Path

import pytest

from modules.script.models import (
    Script,
    ScriptSection,
)
from modules.voice.engine import VoiceEngine
from modules.voice.models import (
    VoiceAlignment,
    VoiceGenerationRequest,
    VoiceGenerationResult,
)


class MockVoiceProvider:
    """Fake provider used for tests."""

    def __init__(self) -> None:
        self.requests: list[
            VoiceGenerationRequest
        ] = []

    def generate(
        self,
        request: VoiceGenerationRequest,
    ) -> VoiceGenerationResult:
        self.requests.append(request)

        return VoiceGenerationResult(
            voice_id=request.voice_id,
            model_id=request.model_id,
            status="completed",
            file_path=str(
                Path(request.output_directory)
                / request.output_filename
            ),
            duration_seconds=480.5,
            character_count=len(request.text),
            alignment=VoiceAlignment(
                characters=list(request.text[:3]),
                character_start_times_seconds=[
                    0.0,
                    0.1,
                    0.2,
                ],
                character_end_times_seconds=[
                    0.1,
                    0.2,
                    0.3,
                ],
            ),
        )


def make_script() -> Script:
    return Script(
        topic="Why Do Pirates Wear Eye Patches?",
        target_duration_seconds=480,
        target_word_count=1200,
        hook="Why do pirates wear eye patches?",
        sections=[
            ScriptSection(
                section_id="s1",
                section_type="hook",
                title="The Pirate Look",
                narration=(
                    "You probably picture a pirate "
                    "with an eye patch."
                ),
                estimated_seconds=45,
                research_sources=["source_001"],
            ),
            ScriptSection(
                section_id="s2",
                section_type="conclusion",
                title="The Answer",
                narration=(
                    "But the famous pirate look "
                    "is mostly a product of culture."
                ),
                estimated_seconds=75,
                research_sources=["source_002"],
            ),
        ],
        total_estimated_seconds=120,
        total_word_count=21,
        closing_message="That is the surprising truth.",
    )


def test_load_script(tmp_path):
    script = make_script()

    script_file = (
        tmp_path / "script.json"
    )

    script_file.write_text(
        script.model_dump_json(indent=2),
        encoding="utf-8",
    )

    engine = VoiceEngine(
        provider=MockVoiceProvider()
    )

    loaded = engine.load_script(
        script_file
    )

    assert loaded.topic == script.topic
    assert len(loaded.sections) == 2


def test_load_missing_script_fails(tmp_path):
    engine = VoiceEngine(
        provider=MockVoiceProvider()
    )

    with pytest.raises(FileNotFoundError):
        engine.load_script(
            tmp_path / "missing.json"
        )


def test_build_narration():
    script = make_script()

    narration = VoiceEngine._build_narration(
        script
    )

    assert (
        "You probably picture a pirate"
        in narration
    )

    assert (
        "famous pirate look"
        in narration
    )

    assert "\n\n" in narration


def test_create_request():
    script = make_script()

    engine = VoiceEngine(
        provider=MockVoiceProvider()
    )

    request = engine.create_request(
        script=script,
        voice_id="ritzz_voice",
        output_directory="output/voice",
    )

    assert request.voice_id == "ritzz_voice"

    assert (
        request.model_id
        == "eleven_multilingual_v2"
    )

    assert (
        "You probably picture a pirate"
        in request.text
    )

    assert (
        request.output_directory
        == "output/voice"
    )

    assert (
        request.output_filename
        == "narration.mp3"
    )


def test_generate():
    provider = MockVoiceProvider()

    engine = VoiceEngine(
        provider=provider
    )

    request = VoiceGenerationRequest(
        voice_id="ritzz_voice",
        text="Test narration.",
        output_directory="output/voice",
        output_filename="narration.mp3",
    )

    result = engine.generate(request)

    assert result.status == "completed"
    assert result.duration_seconds == 480.5

    assert len(provider.requests) == 1


def test_create_voice(tmp_path):
    script = make_script()

    script_file = (
        tmp_path / "script.json"
    )

    script_file.write_text(
        script.model_dump_json(indent=2),
        encoding="utf-8",
    )

    provider = MockVoiceProvider()

    engine = VoiceEngine(
        provider=provider
    )

    result = engine.create_voice(
        script_file=script_file,
        voice_id="ritzz_voice",
        output_directory=tmp_path
        / "voice",
    )

    assert result.status == "completed"

    assert result.file_path == str(
        tmp_path
        / "voice"
        / "narration.mp3"
    )


def test_save_and_load_result(tmp_path):
    result = VoiceGenerationResult(
        voice_id="ritzz_voice",
        model_id="eleven_multilingual_v2",
        status="completed",
        file_path="voice/narration.mp3",
        duration_seconds=480.5,
        character_count=100,
    )

    result_file = (
        tmp_path / "voice.json"
    )

    VoiceEngine.save_result(
        result,
        result_file,
    )

    loaded = VoiceEngine.load_result(
        result_file
    )

    assert loaded.voice_id == "ritzz_voice"
    assert loaded.status == "completed"
    assert loaded.duration_seconds == 480.5


def test_save_result_creates_directory(
    tmp_path,
):
    result = VoiceGenerationResult(
        voice_id="ritzz_voice",
        model_id="eleven_multilingual_v2",
        status="completed",
        file_path="voice/narration.mp3",
        duration_seconds=480.0,
    )

    result_file = (
        tmp_path
        / "nested"
        / "voice"
        / "result.json"
    )

    VoiceEngine.save_result(
        result,
        result_file,
    )

    assert result_file.exists()


def test_completed_result_requires_file_path():
    result = VoiceGenerationResult(
        voice_id="ritzz_voice",
        model_id="eleven_multilingual_v2",
        status="completed",
        duration_seconds=480.0,
    )

    with pytest.raises(ValueError):
        VoiceEngine._validate_result(
            result
        )


def test_completed_result_requires_duration():
    result = VoiceGenerationResult(
        voice_id="ritzz_voice",
        model_id="eleven_multilingual_v2",
        status="completed",
        file_path="voice/narration.mp3",
    )

    with pytest.raises(ValueError):
        VoiceEngine._validate_result(
            result
        )


def test_empty_script_narration_fails():
    script = make_script()

    for section in script.sections:
        section.narration = ""

    with pytest.raises(ValueError):
        VoiceEngine._build_narration(
            script
        )