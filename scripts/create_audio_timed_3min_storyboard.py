import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.storyboard.models import Storyboard
from modules.video.audio_timed_storyboard import AudioTimedStoryboardEngine
from modules.video.sync_engine import VideoSynchronizationEngine
from modules.voice.pilot import PilotNarrationEngine

PILOT_DIRECTORY = PROJECT_ROOT / "projects" / "20260820_001_why_do_pirates_wear_eye_patches" / "pilot_3min"
SOURCE_STORYBOARD = PILOT_DIRECTORY / "storyboard_dynamic.json"
ALIGNMENT_FILE = PILOT_DIRECTORY / PilotNarrationEngine.RESULT_FILENAME
OUTPUT_STORYBOARD = PILOT_DIRECTORY / "storyboard_audio_timed.json"


def main() -> int:
    storyboard = Storyboard.model_validate_json(SOURCE_STORYBOARD.read_text(encoding="utf-8"))
    alignment = VideoSynchronizationEngine.load_narration_alignment(ALIGNMENT_FILE)
    timed = AudioTimedStoryboardEngine().build(storyboard, alignment)
    AudioTimedStoryboardEngine.save_storyboard(timed, OUTPUT_STORYBOARD)
    durations = [scene.duration_seconds for scene in timed.scenes]
    print(f"Audio duration: {alignment.audio_duration_seconds:.3f}s")
    print(f"Narrative scenes: {len(timed.scenes)} (from {len(storyboard.scenes)} storyboard beats)")
    print(f"Typical scene hold: {sorted(durations)[len(durations) // 2]:.3f}s median")
    print(f"Saved: {OUTPUT_STORYBOARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
