import json
from pathlib import Path

import pytest

from modules.voice.models import VoiceAlignment, VoiceGenerationResult
from modules.voice.pilot import PilotNarrationEngine


def storyboard_file(tmp_path: Path) -> Path:
    scenes = []
    for i, line in enumerate(("First beat.", "Second beat."), start=1):
        scenes.append({"scene_id": f"scene_{i:03}", "section_id": "s1", "start_seconds": i - 1,
            "duration_seconds": 1, "narration": line, "visual_description": "A simple pirate illustration.",
            "image_prompt": "A simple pirate illustration."})
    path = tmp_path / "storyboard.json"
    path.write_text(json.dumps({"topic": "Pirates", "target_duration_seconds": 2, "scenes": scenes,
        "total_scene_duration_seconds": 2, "target_scene_duration_seconds": 1}), encoding="utf-8")
    return path


class MockProvider:
    def __init__(self, status="completed"):
        self.status = status
        self.request = None

    def generate(self, request):
        self.request = request
        output = Path(request.output_directory) / request.output_filename
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake mp3")
        return VoiceGenerationResult(voice_id=request.voice_id, model_id=request.model_id,
            status=self.status, file_path=str(output), duration_seconds=2.4, character_count=len(request.text),
            alignment=VoiceAlignment(characters=list(request.text),
                character_start_times_seconds=[i * .01 for i in range(len(request.text))],
                character_end_times_seconds=[(i + 1) * .01 for i in range(len(request.text))]))


def test_generates_dedicated_pilot_audio_and_alignment(tmp_path):
    provider = MockProvider()
    result = PilotNarrationEngine(provider, duration_probe=lambda _: 2.4).generate(
        storyboard_file(tmp_path), tmp_path / "pilot", "voice-1", minimum_duration_seconds=0.5)
    assert provider.request.text == "First beat.\n\nSecond beat."
    assert provider.request.voice_settings.stability == 0.72
    assert provider.request.voice_settings.speed == 0.95
    assert provider.request.output_filename == "narration_3min.mp3"
    assert result.file_path.endswith("narration_3min.mp3")
    assert result.actual_duration_seconds == 2.4
    metadata = tmp_path / "pilot" / "narration_3min_timestamps.json"
    assert metadata.is_file()
    assert json.loads(metadata.read_text(encoding="utf-8"))["alignment"]["characters"] == list(provider.request.text)


def test_rejects_provider_without_alignment(tmp_path):
    class NoAlignment(MockProvider):
        def generate(self, request):
            result = super().generate(request)
            result.alignment = None
            return result
    with pytest.raises(ValueError, match="character timestamps"):
        PilotNarrationEngine(NoAlignment(), duration_probe=lambda _: 2.4).generate(
            storyboard_file(tmp_path), tmp_path / "pilot", "voice-1", minimum_duration_seconds=0.5)


def test_failed_provider_does_not_report_success(tmp_path):
    with pytest.raises(RuntimeError, match="generation failed"):
        PilotNarrationEngine(MockProvider("failed")).generate(
            storyboard_file(tmp_path), tmp_path / "pilot", "voice-1", minimum_duration_seconds=0.5)


def test_empty_scene_narration_is_rejected(tmp_path):
    path = storyboard_file(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scenes"][0]["narration"] = "  "
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Every pilot scene"):
        PilotNarrationEngine(MockProvider()).generate(
            path, tmp_path / "pilot", "voice-1", minimum_duration_seconds=0.5)


def test_preflight_blocks_short_script_before_provider_call(tmp_path):
    provider = MockProvider()
    with pytest.raises(ValueError, match="estimated minimum"):
        PilotNarrationEngine(provider).generate(storyboard_file(tmp_path), tmp_path / "pilot", "voice-1")
    assert provider.request is None


def test_measured_short_audio_is_rejected_and_recorded(tmp_path):
    provider = MockProvider()
    engine = PilotNarrationEngine(provider, duration_probe=lambda _: 0.1)
    with pytest.raises(ValueError, match="short by"):
        engine.generate(storyboard_file(tmp_path), tmp_path / "pilot", "voice-1",
                        minimum_duration_seconds=0.5)
    result_data = json.loads((tmp_path / "pilot" / "narration_3min_timestamps.json").read_text())
    assert result_data["actual_duration_seconds"] == 0.1
    history = json.loads((tmp_path / "pilot" / "narration_duration_history.json").read_text())
    assert history[0]["actual_duration_seconds"] == 0.1
