import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.storyboard.models import Storyboard
from modules.video.engine import VideoAssemblyEngine
from modules.video.pilot_qa import OpenAIImageEditorialReviewer, PilotVideoQA
from modules.video.qa_models import AudioImageMatchReport

PILOT_DIRECTORY = PROJECT_ROOT / "projects" / "20260820_001_why_do_pirates_wear_eye_patches" / "pilot_3min"
REVISION_DIRECTORY = PILOT_DIRECTORY / "revision_v2"
STORYBOARD_FILE = REVISION_DIRECTORY / "storyboard_audio_timed_v2.json"
SYNC_PLAN_FILE = REVISION_DIRECTORY / "video_assembly_plan_v2.json"
REPORT_FILE = REVISION_DIRECTORY / "audio_image_match_report_v2.json"


def main() -> int:
    storyboard = Storyboard.model_validate_json(STORYBOARD_FILE.read_text(encoding="utf-8"))
    plan = VideoAssemblyEngine.load_plan(SYNC_PLAN_FILE)
    reviewer = OpenAIImageEditorialReviewer()
    results = []
    for index, result in enumerate(PilotVideoQA().run_audio_image_match(storyboard, plan, reviewer), start=1):
        results.append(result)
        print(f"{index}/{len(plan.clips)} {result.scene_id}: {result.status}", flush=True)
    report = AudioImageMatchReport(results=results)
    REPORT_FILE.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    counts = report.counts
    print(f"Saved: {REPORT_FILE}")
    print(f"Audio/image match: {counts['PASS']} PASS, {counts['REVIEW']} REVIEW, {counts['FAIL']} FAIL")
    return 0 if counts["REVIEW"] == 0 and counts["FAIL"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
