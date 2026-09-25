import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.storyboard.models import Storyboard
from modules.video.engine import VideoAssemblyEngine
from modules.video.motion_models import MotionInstruction, VideoMotionPlan
from modules.video.pilot_qa import OpenAISemanticReviewer, PilotVideoQA
from modules.video.render_engine import FFmpegVideoRenderer
from modules.video.sync_engine import VideoSynchronizationEngine
from modules.voice.pilot import PilotNarrationEngine
from modules.video.qa_models import PilotQAReport

PILOT_DIRECTORY = PROJECT_ROOT / "projects" / "20260820_001_why_do_pirates_wear_eye_patches" / "pilot_3min"
STORYBOARD_FILE = PILOT_DIRECTORY / "storyboard_dynamic.json"
IMAGE_DIRECTORY = PILOT_DIRECTORY / "images"
AUDIO_FILE = PILOT_DIRECTORY / PilotNarrationEngine.AUDIO_FILENAME
ALIGNMENT_FILE = PILOT_DIRECTORY / PilotNarrationEngine.RESULT_FILENAME
SYNC_PLAN_FILE = PILOT_DIRECTORY / "synced_video_plan_3min.json"
VIDEO_FILE = PILOT_DIRECTORY / "pirates_eye_patch_3min.mp4"
REPORT_FILE = PILOT_DIRECTORY / "pilot_qa_report.json"


def main() -> int:
    semantic_enabled = "--semantic" in sys.argv[1:]
    if not AUDIO_FILE.is_file() or not ALIGNMENT_FILE.is_file():
        raise FileNotFoundError("Generate the dedicated pilot narration before rendering.")
    storyboard = Storyboard.model_validate_json(STORYBOARD_FILE.read_text(encoding="utf-8"))
    assembly_engine = VideoAssemblyEngine()
    initial_plan = assembly_engine.create_plan(storyboard, IMAGE_DIRECTORY, AUDIO_FILE)
    alignment = VideoSynchronizationEngine.load_narration_alignment(ALIGNMENT_FILE)
    sync = VideoSynchronizationEngine()
    synchronized = sync.synchronize_plan(storyboard, initial_plan, alignment)
    assembly_engine.save_plan(synchronized, SYNC_PLAN_FILE)
    motion = VideoMotionPlan(
        topic=synchronized.topic, width=synchronized.width, height=synchronized.height,
        fps=synchronized.fps, total_duration_seconds=synchronized.total_duration_seconds,
        instructions=[MotionInstruction(scene_id=c.scene_id, start_seconds=c.start_seconds,
            duration_seconds=c.duration_seconds, motion="static", zoom_start=1, zoom_end=1,
            position_x_start=.5, position_x_end=.5, position_y_start=.5, position_y_end=.5)
            for c in synchronized.clips],
    )
    renderer = FFmpegVideoRenderer()
    renderer.render(synchronized, motion, AUDIO_FILE, VIDEO_FILE)
    qa = PilotVideoQA()
    technical = qa.run_technical(storyboard, synchronized, AUDIO_FILE, VIDEO_FILE)
    semantic = qa.run_semantic(storyboard, synchronized, OpenAISemanticReviewer()) if semantic_enabled else []
    semantic_status = ("FAIL" if any(x.status == "FAIL" for x in semantic) else
                       "REVIEW" if not semantic or any(x.status == "REVIEW" for x in semantic) else "PASS")
    report = PilotQAReport(technical=technical, semantic_status=semantic_status, semantic=semantic)
    qa.save(report, REPORT_FILE)
    print(f"Video: {VIDEO_FILE}")
    print(f"Technical QA: {technical.status}")
    print("Semantic QA: pending" if not semantic_enabled else
          f"Semantic QA: {sum(x.status == 'PASS' for x in semantic)} PASS, "
          f"{sum(x.status == 'REVIEW' for x in semantic)} REVIEW, "
          f"{sum(x.status == 'FAIL' for x in semantic)} FAIL")
    print(f"Report: {REPORT_FILE}")
    return 0 if technical.status == "PASS" and semantic_status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
