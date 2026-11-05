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


def test_chatterbox_selection_uses_conditionals_fingerprint_and_turbo_model(
    tmp_path,
    monkeypatch,
):
    project_directory = _prepare_project(tmp_path)
    conditionals_file = tmp_path / "voice-conditionals.pt"
    conditionals_file.write_bytes(b"private saved voice conditionals")
    provider_instances = []

    class _FakeChatterboxProvider:
        def __init__(self, *, conditionals_path):
            self.conditionals_path = Path(conditionals_path)
            provider_instances.append(self)

    monkeypatch.setattr(
        run_voice_stage,
        "ProjectManager",
        lambda _path: _FakeProjectManager(_path, project_directory),
    )
    monkeypatch.setattr(run_voice_stage, "VoiceEngine", _FakeVoiceEngine)
    monkeypatch.setattr(
        "modules.voice.chatterbox.ChatterboxTurboProvider",
        _FakeChatterboxProvider,
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", "test-project")
    monkeypatch.setenv("RITZZ_TTS_PROVIDER", "chatterbox")
    monkeypatch.setenv(
        "CHATTERBOX_VOICE_CONDITIONALS_FILE",
        str(conditionals_file),
    )
    monkeypatch.delenv("RITZZ_RESUME", raising=False)
    _FakeVoiceEngine.instances.clear()

    assert run_voice_stage.main() == 0

    assert provider_instances[0].conditionals_path == conditionals_file.resolve()
    result = json.loads(
        (project_directory / "voice" / "narration_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["voice_id"].startswith("chatterbox:")
    assert result["model_id"] == "chatterbox_turbo"


def test_missing_chatterbox_conditionals_fail_before_model_generation(
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
    monkeypatch.setenv("RITZZ_TTS_PROVIDER", "chatterbox")
    monkeypatch.setenv(
        "CHATTERBOX_VOICE_CONDITIONALS_FILE",
        str(tmp_path / "missing-conditionals.pt"),
    )
    monkeypatch.delenv("RITZZ_RESUME", raising=False)

    try:
        run_voice_stage.main()
    except FileNotFoundError as error:
        assert "CHATTERBOX_VOICE_CONDITIONALS_FILE" in str(error)
    else:
        raise AssertionError("Missing Chatterbox reference unexpectedly passed.")


def test_default_provider_remains_elevenlabs(tmp_path, monkeypatch):
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
    assert result["model_id"] == "eleven_v4_turbo"
