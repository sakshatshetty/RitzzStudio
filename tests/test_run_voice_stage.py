import json
from pathlib import Path
from typing import ClassVar

from modules.project.config import ProductionConfig
from modules.voice.models import VoiceAlignment, VoiceGenerationResult
from scripts import run_voice_stage


class _FakeProjectManager:
    def __init__(self, _projects_directory: Path, project_directory: Path) -> None:
        self.project_directory = project_directory

    def load_project(self, _project_id: str):
        return object()

    def get_project_path(self, _project):
        return self.project_directory


class _FakeVoiceEngine:
    instances: ClassVar[list["_FakeVoiceEngine"]] = []

    def __init__(self, provider) -> None:
        self.provider = provider
        self.instances.append(self)

    def create_voice(self, **kwargs):
        self.create_voice_kwargs = kwargs
        output_path = Path(kwargs["output_directory"]) / "narration.mp3"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake narration")
        return VoiceGenerationResult(
            voice_id=kwargs["voice_id"],
            model_id=kwargs["model_id"],
            status="completed",
            file_path=str(output_path),
            duration_seconds=1.0,
            alignment=VoiceAlignment(
                characters=["x"],
                character_start_times_seconds=[0.0],
                character_end_times_seconds=[0.1],
            ),
        )

    @staticmethod
    def save_result(result, output_file):
        Path(output_file).write_text(result.model_dump_json(), encoding="utf-8")


def _prepare_project(tmp_path: Path) -> Path:
    project_directory = tmp_path / "project"
    (project_directory / "script").mkdir(parents=True)
    (project_directory / "script" / "script.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (project_directory / "production_config.json").write_text(
        ProductionConfig().model_dump_json(),
        encoding="utf-8",
    )
    return project_directory


def test_smallestai_selection_uses_project_voice_model_language_and_speed(
    tmp_path,
    monkeypatch,
):
    project_directory = _prepare_project(tmp_path)
    (project_directory / "production_config.json").write_text(
        ProductionConfig(
            smallest_model="lightning_v3.1",
            smallest_voice_id="voice_from_project_config",
            smallest_language="hi",
            voice_speed=1.0,
        ).model_dump_json(),
        encoding="utf-8",
    )
    provider = object()
    provider_kwargs = {}

    monkeypatch.setattr(
        run_voice_stage,
        "ProjectManager",
        lambda _path: _FakeProjectManager(_path, project_directory),
    )
    monkeypatch.setattr(run_voice_stage, "VoiceEngine", _FakeVoiceEngine)
    monkeypatch.setattr(
        run_voice_stage,
        "SmallestAIProvider",
        lambda **kwargs: provider_kwargs.update(kwargs) or provider,
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", "test-project")
    monkeypatch.setenv("RITZZ_TTS_PROVIDER", "smallestai")
    monkeypatch.setenv("SMALLEST_API_KEY", "test-api-key")
    monkeypatch.setenv("SMALLEST_VOICE_ID", "must_not_override_config")
    monkeypatch.setenv("SMALLEST_MODEL", "must_not_override_config")
    monkeypatch.setenv("SMALLEST_LANGUAGE", "must_not_override_config")
    monkeypatch.delenv("RITZZ_RESUME", raising=False)
    _FakeVoiceEngine.instances.clear()

    assert run_voice_stage.main() == 0

    assert _FakeVoiceEngine.instances[0].provider is provider
    result = json.loads(
        (project_directory / "voice" / "narration_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["voice_id"] == "voice_from_project_config"
    assert result["model_id"] == "lightning_v3.1"
    assert provider_kwargs == {"language": "hi"}
    assert _FakeVoiceEngine.instances[0].create_voice_kwargs[
        "production_config"
    ].voice_speed == 1.0


def test_smallest_api_key_is_not_saved_in_voice_metadata(
    tmp_path,
    monkeypatch,
):
    project_directory = _prepare_project(tmp_path)
    monkeypatch.setattr(
        run_voice_stage,
        "ProjectManager",
        lambda _path: _FakeProjectManager(_path, project_directory),
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", "test-project")
    monkeypatch.setenv("RITZZ_TTS_PROVIDER", "smallestai")
    monkeypatch.setenv("SMALLEST_API_KEY", "sensitive-api-key")
    monkeypatch.delenv("RITZZ_RESUME", raising=False)
    _FakeVoiceEngine.instances.clear()

    monkeypatch.setattr(run_voice_stage, "VoiceEngine", _FakeVoiceEngine)
    provider = object()
    monkeypatch.setattr(
        run_voice_stage,
        "SmallestAIProvider",
        lambda **_kwargs: provider,
    )
    assert run_voice_stage.main() == 0

    result_text = (
        project_directory / "voice" / "narration_result.json"
    ).read_text(encoding="utf-8")
    result = json.loads(result_text)
    assert result["voice_id"] == "voice_CNOBFXW1SC"
    assert "sensitive-api-key" not in result_text


def test_explicit_elevenlabs_selection_preserves_existing_voice(
    tmp_path,
    monkeypatch,
):
    project_directory = _prepare_project(tmp_path)
    provider = object()
    monkeypatch.setattr(
        run_voice_stage,
        "ProjectManager",
        lambda _path: _FakeProjectManager(_path, project_directory),
    )
    monkeypatch.setattr(run_voice_stage, "VoiceEngine", _FakeVoiceEngine)
    monkeypatch.setattr(
        run_voice_stage,
        "ElevenLabsProvider",
        lambda: provider,
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", "test-project")
    monkeypatch.setenv("RITZZ_VOICE_ID", "existing-voice")
    monkeypatch.setenv("RITZZ_TTS_PROVIDER", "elevenlabs")
    monkeypatch.delenv("RITZZ_RESUME", raising=False)
    _FakeVoiceEngine.instances.clear()

    assert run_voice_stage.main() == 0

    assert _FakeVoiceEngine.instances[0].provider is provider
    result = json.loads(
        (project_directory / "voice" / "narration_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["model_id"] == "eleven_turbo_v2_5"


def test_default_provider_is_smallestai(tmp_path, monkeypatch):
    project_directory = _prepare_project(tmp_path)
    (project_directory / "production_config.json").write_text(
        ProductionConfig().model_dump_json(),
        encoding="utf-8",
    )
    provider = object()
    monkeypatch.setattr(
        run_voice_stage,
        "ProjectManager",
        lambda _path: _FakeProjectManager(_path, project_directory),
    )
    monkeypatch.setattr(run_voice_stage, "VoiceEngine", _FakeVoiceEngine)
    monkeypatch.setattr(
        run_voice_stage,
        "SmallestAIProvider",
        lambda **_kwargs: provider,
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", "test-project")
    monkeypatch.setenv("SMALLEST_API_KEY", "test-api-key")
    monkeypatch.delenv("RITZZ_TTS_PROVIDER", raising=False)
    monkeypatch.delenv("RITZZ_RESUME", raising=False)
    _FakeVoiceEngine.instances.clear()

    assert run_voice_stage.main() == 0

    assert _FakeVoiceEngine.instances[0].provider is provider
    result = json.loads(
        (project_directory / "voice" / "narration_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["voice_id"] == "voice_CNOBFXW1SC"
    assert result["model_id"] == "lightning_v3.1_pro"
    assert _FakeVoiceEngine.instances[0].create_voice_kwargs[
        "production_config"
    ].voice_speed == 0.92
