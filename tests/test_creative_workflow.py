from pathlib import Path

WORKFLOW = Path(".github/workflows/ritzz-creative-production.yml")


def test_primary_workflow_uses_supplied_creative_and_gates_private_upload():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    required_steps = [
        "Validate and import the creative ZIP",
        "Generate or reuse supplied-script narration",
        "Research factual visual context",
        "Build context-driven audio-timed storyboard",
        "Generate or resume scene images",
        "Render and run technical plus targeted semantic QA",
        "Create exact-input final review package",
        "Human review and private YouTube upload",
    ]
    positions = [workflow.index(step) for step in required_steps]
    assert positions == sorted(positions)
    assert "environment:\n      name: ritzz-packaging-approval" in workflow
    assert "run_private_upload_stage.py" in workflow
    assert "upload_youtube_thumbnail.py" in workflow
    assert "RITZZ_HUMAN_APPROVED: \"true\"" in workflow
    assert "public" not in workflow.casefold()


def test_primary_workflow_does_not_run_legacy_creative_generation():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for forbidden_step in (
        "discover_pipeline_topics.py",
        "select_pipeline_topic.py",
        "run_approved_content_workflow.py",
        "run_metadata_packaging.py",
        "run_thumbnail_packaging.py",
    ):
        assert forbidden_step not in workflow

    legacy = Path(".github/workflows/ritzz-pipeline.yml").read_text(
        encoding="utf-8"
    )
    assert legacy.startswith("name: RITZZ Legacy Generated-Creative Pipeline")


def test_new_production_downloads_zip_from_a_github_release_asset():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "creative_package_release_tag:" in workflow
    assert "python scripts/download_creative_package.py" in workflow
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert "creative_package_url" not in workflow
    assert "RITZZ_CREATIVE_PACKAGE_HOST" not in workflow
    assert "RITZZ_CREATIVE_PACKAGE_DOWNLOAD_TOKEN" not in workflow


def test_project_archive_steps_brace_ids_before_appending_wildcards():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '-name "${PROJECT_ID}_*"' in workflow
    assert '-name "${RITZZ_PROJECT_ID}_*"' in workflow
    assert '-name "$PROJECT_ID_*"' not in workflow
    assert '-name "$RITZZ_PROJECT_ID_*"' not in workflow
