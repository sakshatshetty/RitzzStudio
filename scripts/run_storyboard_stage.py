"""Build the narrative and audio-timed storyboards for a project."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.image.character_profile import load_character_profile
from modules.image.prompt_builder import ImagePromptBuilder
from modules.project.config import ProductionConfig
from modules.project.manager import ProjectManager
from modules.research.models import Research
from modules.storyboard.engine import StoryboardEngine
from modules.storyboard.models import Storyboard
from modules.storyboard.visual_context import VisualContextEngine
from modules.video.audio_timed_storyboard import AudioTimedStoryboardEngine
from modules.video.sync_engine import VideoSynchronizationEngine


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    project_manager = ProjectManager(Path("projects"))
    project = project_manager.load_project(project_id)
    project_directory = project_manager.get_project_path(project)
    script_file = project_directory / "script" / "script.json"
    config_file = project_directory / "production_config.json"
    narration_result_file = project_directory / "voice" / "narration_result.json"
    storyboard_directory = project_directory / "storyboard"
    narrative_file = storyboard_directory / "storyboard.json"
    timed_file = storyboard_directory / "storyboard_audio_timed.json"

    config = ProductionConfig.model_validate_json(config_file.read_text(encoding="utf-8"))
    narrative = StoryboardEngine(
        target_scene_duration_seconds=(
            config.scene_minimum_duration_seconds
            + config.scene_maximum_duration_seconds
        ) / 2,
    ).create_storyboard(
        script_file=script_file,
        output_file=narrative_file,
        production_config=config,
    )
    alignment = VideoSynchronizationEngine.load_narration_alignment(narration_result_file)
    timed = AudioTimedStoryboardEngine(production_config=config).build(narrative, alignment)
    research = Research.model_validate_json(
        (project_directory / "research" / "research.json").read_text(
            encoding="utf-8"
        )
    )
    timed, visual_world, contracts = VisualContextEngine().plan(
        research,
        timed,
        project_directory,
    )
    prompt_builder = ImagePromptBuilder(
        character_profile=load_character_profile(project_directory),
        visual_world=visual_world,
    )
    timed = timed.model_copy(update={
        "scenes": [
            scene.model_copy(
                update={"image_prompt": prompt_builder.build(scene)}
            )
            for scene in timed.scenes
        ]
    })
    AudioTimedStoryboardEngine.save_storyboard(timed, timed_file, config)
    Storyboard.model_validate_json(timed_file.read_text(encoding="utf-8"))
    print(f"Narrative storyboard: {narrative_file} ({len(narrative.scenes)} scenes)")
    print(f"Audio-timed storyboard: {timed_file} ({len(timed.scenes)} scenes)")
    print(f"Visual world bible: {project_directory / 'visual_world_bible.json'}")
    print(f"Scene visual contracts: {len(contracts)}")
    print(f"Audio duration: {alignment.audio_duration_seconds:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
