import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.storyboard.models import Storyboard
from modules.video.engine import VideoAssemblyEngine
from modules.video.motion_models import MotionInstruction, VideoMotionPlan
from modules.video.render_engine import FFmpegVideoRenderer
from modules.voice.pilot import PilotNarrationEngine

PILOT_DIRECTORY = PROJECT_ROOT / "projects" / "20260820_001_why_do_pirates_wear_eye_patches" / "pilot_3min"
STORYBOARD_FILE = PILOT_DIRECTORY / "storyboard_audio_timed.json"
IMAGE_DIRECTORY = PILOT_DIRECTORY / "images_audio_timed"
AUDIO_FILE = PILOT_DIRECTORY / PilotNarrationEngine.AUDIO_FILENAME
OUTPUT_FILE = PILOT_DIRECTORY / "pirates_eye_patch_audio_timed_3min.mp4"


def main() -> int:
    storyboard = Storyboard.model_validate_json(STORYBOARD_FILE.read_text(encoding="utf-8"))
    plan = VideoAssemblyEngine().create_plan(storyboard, IMAGE_DIRECTORY, AUDIO_FILE)
    motion = VideoMotionPlan(
        topic=plan.topic, width=plan.width, height=plan.height, fps=plan.fps,
        total_duration_seconds=plan.total_duration_seconds,
        instructions=[MotionInstruction(scene_id=clip.scene_id, start_seconds=clip.start_seconds,
            duration_seconds=clip.duration_seconds, motion="static", zoom_start=1, zoom_end=1,
            position_x_start=.5, position_x_end=.5, position_y_start=.5, position_y_end=.5)
            for clip in plan.clips],
    )
    output = FFmpegVideoRenderer().render(plan, motion, AUDIO_FILE, OUTPUT_FILE)
    print(f"Rendered audio-timed pilot with {len(plan.clips)} scenes: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
