from pathlib import Path

WORKFLOW = Path(".github/workflows/ritzz-creative-production.yml")


def test_primary_workflow_uses_supplied_creative_and_gates_private_upload():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    required_steps = [
        "Verify selected YouTube channel access",
        "Validate and import the creative ZIP",
        "Generate or reuse supplied-script narration",
        "Time supplied Flow storyboard against narration",
        "Render supplied stills and run technical QA",
        "Create exact-input final review package",
        "Prepare MP4-only review download",
        "Upload MP4-only review video",
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


def test_primary_workflow_selects_a_channel_and_uses_its_oauth_token():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    dispatch_inputs = workflow.split("  creative_package_release_tag:", 1)[0]

    for channel in ("Ritzz-Explains", "RitzzHistory", "RitzzTech1"):
        assert f"          - {channel}" in dispatch_inputs
        assert f"inputs.youtube_channel == '{channel}'" in workflow
    assert "secrets.GOOGLE_TOKEN_B64" in workflow
    assert (
        "inputs.youtube_channel == 'RitzzHistory' && "
        "secrets.GOOGLE_TOKEN_RITZZ_HISTORY_B64"
    ) in workflow
    assert (
        "inputs.youtube_channel == 'RitzzTech1' && "
        "secrets.GOOGLE_TOKEN_RITZZ_TECH_B64"
    ) in workflow
    assert "|| '' }}" in workflow
    assert "RITZZ_YOUTUBE_CHANNEL_TITLE:" in workflow
    assert "Selected YouTube channel:" in workflow
    assert "python scripts/verify_youtube_channel.py" in workflow


def test_workflow_avoids_apt_and_pins_the_rendering_font_download():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ffmpeg_action = Path(".github/actions/setup-ffmpeg/action.yml").read_text(
        encoding="utf-8"
    )

    assert "sudo apt-get" not in workflow
    assert workflow.count("uses: ./.github/actions/setup-ffmpeg") == 3
    assert "command -v ffmpeg" not in workflow
    assert "command -v ffprobe" not in workflow
    assert "autobuild-2026-10-21-13-06" in ffmpeg_action
    assert "ffmpeg-N-127900-ge2798d5cad-linux64-gpl.tar.xz" in ffmpeg_action
    assert (
        "cf339ce89e952120f6e01e57718c1e2e3c1914107ae81649a88156caa5cd6632"
        in ffmpeg_action
    )
    assert 'echo "$install_dir/bin" >> "$GITHUB_PATH"' in ffmpeg_action
    assert 'echo "RITZZ_FFPROBE_PATH=$install_dir/bin/ffprobe"' in ffmpeg_action
    assert '"$install_dir/bin/ffmpeg" -version' in ffmpeg_action
    assert '"$install_dir/bin/ffprobe" -version' in ffmpeg_action
    assert "google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6" in workflow
    assert "ComicNeue-Bold.ttf" in workflow
    assert 'RITZZ_FONT_PATH=$RUNNER_TEMP/ritzz-fonts/ComicNeue-Bold.ttf' in workflow


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

    assert workflow.count("uses: actions/upload-artifact@v4") == 4
    assert workflow.count("include-hidden-files: true") == 3


def test_preapproval_review_artifact_contains_only_the_rendered_mp4():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    production = workflow.split("  human-review-and-private-upload:\n", 1)[0]
    prepare_video = production.split(
        "      - name: Prepare MP4-only review download\n", 1
    )[1].split("      - name: Upload MP4-only review video\n", 1)[0]
    upload_video = production.split(
        "      - name: Upload MP4-only review video\n", 1
    )[1].split("      - name: Publish review link\n", 1)[0]

    assert 'find projects -mindepth 1 -maxdepth 1 -type d -name "${PROJECT_ID}_*"' in prepare_video
    assert 'video/ritzz_test.mp4' in prepare_video
    assert '.pipeline-artifacts/review-video/${PROJECT_ID}.mp4' in prepare_video
    assert "name: ritzz-review-video-" in upload_video
    assert "path: .pipeline-artifacts/review-video/${{" in upload_video
    assert "if-no-files-found: error" in upload_video
    assert "extract the MP4 into your local Downloads folder" in production
    assert "gh run download ${GITHUB_RUN_ID}" in production
    assert r"\$env:USERPROFILE\\Downloads" in production


def test_human_review_downloads_checkpoint_from_the_current_workflow_run():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    human_review = workflow.split("  human-review-and-private-upload:\n", 1)[1]
    download_step = human_review.split(
        "      - name: Restore project and prepare OAuth files\n", 1
    )[0]
    resume_download_step = workflow.split(
        "      - name: Download saved project checkpoint\n", 1
    )[1].split("      - name: Restore saved project\n", 1)[0]

    assert "uses: actions/download-artifact@v4" in download_step
    assert "run-id:" not in download_step
    assert "github-token:" not in download_step
    assert "run-id: ${{ inputs.source_run_id }}" in resume_download_step
    assert "github-token: ${{ github.token }}" in resume_download_step


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
