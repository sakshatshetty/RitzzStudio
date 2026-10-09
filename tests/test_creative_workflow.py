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
        "Enforce text-free images, render, and run technical QA",
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


def test_checkpoint_uploads_include_hidden_artifact_directory_files():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("uses: actions/upload-artifact@v4") == 3
    assert workflow.count("include-hidden-files: true") == 3


def test_resume_workflow_exposes_stage_rerun_choices_and_reuse_controls():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for stage in (
        "CONTINUE",
        "NARRATION",
        "RESEARCH",
        "STORYBOARD",
        "IMAGES",
        "RENDER",
        "FINAL_PACKAGE",
    ):
        assert f"          - {stage}" in workflow

    assert "RITZZ_FORCE_RESEARCH:" in workflow
    assert "RITZZ_FORCE_REGENERATE_IMAGES:" in workflow
    assert "RITZZ_RERUN_FROM_STAGE:" in workflow
    assert (
        "RITZZ_RESUME: ${{ inputs.mode == 'RESUME' && "
        "inputs.rerun_from_stage != 'NARRATION'"
    ) in workflow
    assert (
        "inputs.rerun_from_stage == 'CONTINUE' || "
        "inputs.rerun_from_stage == 'IMAGES' || "
        "inputs.rerun_from_stage == 'RENDER'"
    ) in workflow
    assert "inputs.rerun_from_stage == 'RESEARCH'" in workflow
    assert "inputs.rerun_from_stage == 'IMAGES'" in workflow
    assert workflow.count("inputs.rerun_from_stage != 'FINAL_PACKAGE'") == 5


def test_workflow_selects_flux_or_gpt_image_backend_without_prompt_changes():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "      image_model:" in workflow
    assert "          - FLUX_SCHNELL" in workflow
    assert "          - GPT_IMAGE_2" in workflow
    assert "        default: FLUX_SCHNELL" in workflow
    assert "REPLICATE_API_TOKEN: ${{ secrets.REPLICATE_API_TOKEN }}" in workflow
    assert "python scripts/validate_pipeline_prerequisites.py" in workflow
    assert '--image-model "$RITZZ_IMAGE_MODEL"' in workflow
