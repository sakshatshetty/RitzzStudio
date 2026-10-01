import json

import pytest

from modules.production_state import (
    PIPELINE_STAGES,
    ProductionStateError,
    ProductionStateStore,
)


def test_new_production_initializes_all_stages(tmp_path):
    store = ProductionStateStore(tmp_path / "production_state.json")

    state = store.initialize("prod-123")

    assert state["production_id"] == "prod-123"
    assert state["status"] == "in_progress"
    assert tuple(state["stages"]) == PIPELINE_STAGES
    assert all(stage["status"] == "pending" for stage in state["stages"].values())


def test_new_production_rejects_existing_state(tmp_path):
    store = ProductionStateStore(tmp_path / "production_state.json")
    store.initialize("prod-123")

    with pytest.raises(ProductionStateError, match="PRODUCTION_ALREADY_EXISTS"):
        store.initialize("prod-123")


def test_resume_reuses_completed_stages_and_retries_failed_stage(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    output = artifact_root / "candidates.json"
    candidates = artifact_root / "topic_candidates.json"
    candidates.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "candidate-1",
                        "topic": "A reusable topic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output.write_text('{"candidates": []}', encoding="utf-8")
    store = ProductionStateStore(artifact_root / "production_state.json", artifact_root)
    store.initialize("prod-123")
    store.start_stage("topic_discovery")
    store.complete_stage("topic_discovery", ["topic_candidates.json"])
    store.start_stage("topic_selection")
    store.fail_stage("topic_selection", "approval timed out")

    resumed = store.resume("prod-123")
    assert resumed["stages"]["topic_discovery"]["status"] == "completed"
    assert resumed["stages"]["topic_selection"]["status"] == "failed"

    store.start_stage("topic_selection")
    selection = artifact_root / "selection.json"
    selection.write_text(
        json.dumps({"topic": "A reusable topic", "candidate_id": "candidate-1"}),
        encoding="utf-8",
    )
    (artifact_root / "topic_selection.json").write_text(
        selection.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    store.complete_stage("topic_selection", ["topic_selection.json"])
    retried = store.resume("prod-123")
    assert retried["stages"]["topic_selection"]["attempts"] == 2
    assert retried["stages"]["topic_selection"]["status"] == "completed"


def test_resume_reports_missing_production_and_wrong_production_id(tmp_path):
    store = ProductionStateStore(tmp_path / "production_state.json")
    with pytest.raises(ProductionStateError, match="PRODUCTION_NOT_FOUND"):
        store.resume("prod-missing")
    store.initialize("prod-123")

    with pytest.raises(ProductionStateError, match="STATE_ARTIFACT_MISMATCH"):
        store.resume("prod-other")


def test_resume_detects_missing_or_modified_completed_artifact(tmp_path):
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    output = artifact_root / "selection.json"
    output.write_text(json.dumps({"topic": "initial"}), encoding="utf-8")
    store = ProductionStateStore(artifact_root / "production_state.json", artifact_root)
    store.initialize("prod-123")
    store.start_stage("topic_selection")
    store.complete_stage("topic_selection", ["selection.json"])

    output.write_text(json.dumps({"topic": "changed"}), encoding="utf-8")
    with pytest.raises(ProductionStateError, match="STATE_ARTIFACT_MISMATCH"):
        store.resume("prod-123")


def test_private_upload_intent_allows_only_its_original_attempt(tmp_path):
    state_file = tmp_path / "production_state.json"
    store = ProductionStateStore(state_file)
    store.initialize("prod-123")
    store.start_stage("private_upload")
    store.set_private_upload_intent("run-1", 1)

    store.validate_private_upload_intent("run-1", 1)
    with pytest.raises(
        ProductionStateError,
        match="PUBLISH_ATTEMPT_RECONCILIATION_REQUIRED",
    ):
        store.validate_private_upload_intent("run-2", 1)
    with pytest.raises(
        ProductionStateError,
        match="PUBLISH_ATTEMPT_RECONCILIATION_REQUIRED",
    ):
        store.set_private_upload_intent("run-1", 2)
