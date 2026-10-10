from pathlib import Path

WORKFLOW = Path(".github/workflows/ritzz-creative-production.yml")


def test_primary_workflow_uses_supplied_creative_and_gates_private_upload():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    required_steps = [
        "Validate and import the creative ZIP",
        "Generate or reuse supplied-script narration",
        "Time supplied Flow storyboard against narration",
        "Render supplied stills and run technical QA",
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
    assert "OPENAI_API_KEY" not in workflow
    assert "REPLICATE_API_TOKEN" not in workflow
    assert "run_image_stage.py" not in workflow
    assert "run_creative_research.py" not in workflow


def test_primary_workflow_keeps_legacy_topic_discovery_separate():
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


def test_checkpoint_uploads_include_hidden_artifact_directory_files():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("uses: actions/upload-artifact@v4") == 3
    assert workflow.count("include-hidden-files: true") == 3


def test_resume_workflow_exposes_only_remaining_local_production_stages():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for stage in (
        "CONTINUE",
        "NARRATION",
        "STORYBOARD",
        "RENDER",
        "FINAL_PACKAGE",
    ):
        assert f"          - {stage}" in workflow

    assert "RITZZ_RERUN_FROM_STAGE:" in workflow
    assert (
        "RITZZ_RESUME: ${{ inputs.mode == 'RESUME' && "
        "inputs.rerun_from_stage != 'NARRATION'"
    ) in workflow
    assert (
        "inputs.rerun_from_stage != 'NARRATION'"
    ) in workflow
    assert "inputs.rerun_from_stage == 'STORYBOARD'" in workflow
    assert workflow.count("inputs.rerun_from_stage != 'FINAL_PACKAGE'") == 2


def test_workflow_does_not_select_or_generate_image_backend():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    render_stage = Path("scripts/run_render_stage.py").read_text(encoding="utf-8")

    assert "image_model:" not in workflow
    assert "RITZZ_IMAGE_MODEL" not in workflow
    assert "OPENAI_API_KEY" not in workflow
    assert "REPLICATE_API_TOKEN" not in workflow
    assert "python scripts/run_storyboard_stage.py" in workflow
    assert "python scripts/run_render_stage.py" in workflow
    assert "OpenAIImageProvider" not in render_stage
    assert "_review_and_repair_images" not in render_stage
