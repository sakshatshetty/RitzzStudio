import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.storyboard.models import Storyboard
from modules.video.engine import VideoAssemblyEngine
from modules.video.pilot_qa import OpenAISemanticReviewer, PilotVideoQA
from modules.video.qa_models import PilotQAReport
from modules.video.sync_engine import VideoSynchronizationEngine
from modules.voice.pilot import PilotNarrationEngine

PILOT_DIRECTORY = PROJECT_ROOT / "projects" / "20260820_001_why_do_pirates_wear_eye_patches" / "pilot_3min"
STORYBOARD_FILE = PILOT_DIRECTORY / "storyboard_dynamic.json"
ALIGNMENT_FILE = PILOT_DIRECTORY / PilotNarrationEngine.RESULT_FILENAME
AUDIO_FILE = PILOT_DIRECTORY / PilotNarrationEngine.AUDIO_FILENAME
VIDEO_FILE = PILOT_DIRECTORY / "pirates_eye_patch_3min.mp4"
REPORT_FILE = PILOT_DIRECTORY / "pilot_qa_report.json"


def main() -> int:
    semantic_enabled = "--technical-only" not in sys.argv[1:]
    storyboard = Storyboard.model_validate_json(STORYBOARD_FILE.read_text(encoding="utf-8"))
    images = PILOT_DIRECTORY / "images"
    assembly = VideoAssemblyEngine().create_plan(storyboard, images, AUDIO_FILE)
    alignment = VideoSynchronizationEngine.load_narration_alignment(ALIGNMENT_FILE)
    plan = VideoSynchronizationEngine().synchronize_plan(storyboard, assembly, alignment)
    VideoAssemblyEngine.save_plan(plan, PILOT_DIRECTORY / "synced_video_plan_3min.json")
    qa = PilotVideoQA()
    technical = qa.run_technical(storyboard, plan, AUDIO_FILE, VIDEO_FILE if VIDEO_FILE.exists() else None)
    semantic = qa.run_semantic(storyboard, plan, OpenAISemanticReviewer()) if semantic_enabled else []
    semantic_status = ("FAIL" if any(x.status == "FAIL" for x in semantic) else
                       "REVIEW" if not semantic or any(x.status == "REVIEW" for x in semantic) else "PASS")
    report = PilotQAReport(technical=technical, semantic_status=semantic_status, semantic=semantic)
    qa.save(report, REPORT_FILE)
    print(f"Technical QA: {technical.status}")
    print(f"Images checked: {technical.checks['images']}; timeline drift: {technical.maximum_timeline_drift_seconds:.3f}s")
    print(f"Semantic: {sum(x.status == 'PASS' for x in semantic)} PASS, {sum(x.status == 'REVIEW' for x in semantic)} REVIEW, {sum(x.status == 'FAIL' for x in semantic)} FAIL")
    print(f"Report: {REPORT_FILE}")
    return 0 if technical.status == "PASS" and all(x.status == "PASS" for x in semantic) else 2


if __name__ == "__main__":
    raise SystemExit(main())
