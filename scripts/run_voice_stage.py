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
from modules.voice.elevenlabs import ElevenLabsProvider
from modules.voice.engine import VoiceEngine


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
    result = engine.create_voice(
        script_file=script_file,
        voice_id=voice_id,
        output_directory=voice_directory,
        production_config=config,
    )
    result_path = voice_directory / "narration_result.json"
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
