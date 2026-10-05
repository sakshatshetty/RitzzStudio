import json
from pathlib import Path

from modules.qa.engine import load_project_qa, qa_report_path, record_stage_qa
from modules.qa.models import QAStageResult


def test_stage_qa_attempts_persist_and_latest_result_controls_status(tmp_path: Path):
    record_stage_qa(
        tmp_path,
        QAStageResult(stage="images", status="FAIL", findings=["Scene mismatch"]),
    )
    report = record_stage_qa(
        tmp_path,
        QAStageResult(stage="images", status="PASS"),
    )

    loaded = load_project_qa(tmp_path)
    assert report.status == "PASS"
    assert loaded.status == "PASS"
    assert [item.attempt for item in loaded.stages["images"]] == [1, 2]
    assert qa_report_path(tmp_path).exists()


def test_project_qa_aggregates_latest_status_across_stages(tmp_path: Path):
    record_stage_qa(tmp_path, QAStageResult(stage="script", status="PASS"))
    record_stage_qa(tmp_path, QAStageResult(stage="storyboard", status="REVIEW"))

    assert load_project_qa(tmp_path).status == "REVIEW"

    record_stage_qa(tmp_path, QAStageResult(stage="storyboard", status="FAIL"))
    assert load_project_qa(tmp_path).status == "FAIL"


def test_legacy_qa_attempts_infer_stage_from_report_key(tmp_path: Path):
    path = qa_report_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "stages": {
                    "technical_qa": [{"status": "PASS"}],
                    "rendered_semantic_qa": [{"status": "REVIEW"}],
                }
            }
        ),
        encoding="utf-8",
    )

    report = record_stage_qa(
        tmp_path,
        QAStageResult(stage="metadata_packaging", status="PASS"),
    )

    assert report.status == "REVIEW"
    assert report.stages["technical_qa"][0].stage == "technical_qa"
    assert report.stages["rendered_semantic_qa"][0].stage == "rendered_semantic_qa"
