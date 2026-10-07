"""Generate and validate narration for the approved project."""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.config import ProductionConfig
from modules.project.manager import ProjectManager
from modules.video.sync_engine import VideoSynchronizationEngine
from modules.voice.elevenlabs import ElevenLabsProvider
from modules.voice.engine import VoiceEngine
from modules.voice.models import VoiceGenerationResult


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    project_manager = ProjectManager(Path("projects"))
    project = project_manager.load_project(project_id)
    project_directory = project_manager.get_project_path(project)
    script_file = project_directory / "script" / "script.json"
    config_file = project_directory / "production_config.json"
    voice_directory = project_directory / "voice"
    if not script_file.exists() or not config_file.exists():
        raise FileNotFoundError("Approved project script or production configuration is missing.")

    config = ProductionConfig.model_validate_json(config_file.read_text(encoding="utf-8"))
    voice_id = os.environ.get("RITZZ_VOICE_ID")
    if not voice_id:
        raise RuntimeError("RITZZ_VOICE_ID is not configured.")

    engine = VoiceEngine(ElevenLabsProvider())
    result_path = voice_directory / "narration_result.json"
    audio_file = voice_directory / "narration.mp3"
    if os.environ.get("RITZZ_RESUME") == "true" and (
        result_path.exists() or audio_file.exists()
    ):
        if not result_path.is_file() or not audio_file.is_file():
            raise RuntimeError(
                "Saved narration is incomplete; refusing to overwrite or reuse it."
            )
        result = VoiceGenerationResult.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
        if (
            result.status != "completed"
            or result.voice_id != voice_id
            or not result.alignment
            or not result.file_path
            or not Path(result.file_path).is_file()
        ):
            raise RuntimeError(
                "Saved narration is not a completed, aligned asset from the configured voice."
            )
        script = engine.load_script(script_file)
        expected_text = engine._build_narration(script)
        aligned_text = "".join(result.alignment.characters)
        if (
            VideoSynchronizationEngine._compact_text(expected_text)
            != VideoSynchronizationEngine._compact_text(aligned_text)
        ):
            raise RuntimeError(
                "Saved narration alignment does not match the immutable supplied script."
            )
        engine._validate_result(result)
        duration = result.actual_duration_seconds or result.duration_seconds
        if duration is None or duration < config.minimum_duration_seconds:
            raise RuntimeError(
                "Saved narration does not meet the configured minimum duration."
            )
        print(
            f"Reusing saved narration and alignment ({duration:.3f}s); "
            "no additional voice API call was made."
        )
        return 0
    result = engine.create_voice(
        script_file=script_file,
        voice_id=voice_id,
        output_directory=voice_directory,
        production_config=config,
    )
    engine.save_result(result, result_path)
    if result.status != "completed":
        raise RuntimeError(result.error_message or "Narration generation failed.")
    if not result.alignment:
        raise RuntimeError("Narration completed without character alignment.")

    print(json.dumps({
        "project_id": project_id,
        "audio_file": result.file_path,
        "narration_result": str(result_path),
        "duration_seconds": result.actual_duration_seconds or result.duration_seconds,
        "status": result.status,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
