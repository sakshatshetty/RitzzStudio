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
        "Upload production checkpoint and final package",
    ]
    positions = [workflow.index(step) for step in required_steps]
    assert positions == sorted(positions)
    assert "human-review-and-private-upload:" not in workflow
    assert "ritzz-packaging-approval" not in workflow
    assert "run_private_upload_stage.py" not in workflow
    assert "RITZZ_HUMAN_APPROVED" not in workflow
    assert "public" not in workflow.casefold()
    assert "OPENAI_API_KEY" not in workflow
    assert "REPLICATE_API_TOKEN" not in workflow
    assert "run_image_stage.py" not in workflow
    assert "run_creative_research.py" not in workflow


def test_windows_creative_builder_matches_current_wpm_and_scene_limits():
    builder = Path("creative_work.ps1").read_text(encoding="utf-8")

    assert "$storyboard.scenes.Count -gt 249" in builder
    assert "$sceneWordCount -gt 22" in builder
    assert "170 words per minute" in builder
    assert "$actualWordCount / 22.0" in builder
    assert "between 1 and 200 scenes" not in builder
    assert "140 words per minute" not in builder


def test_windows_creative_builder_stops_tags_at_sources_heading():
    builder = Path("creative_work.ps1").read_text(encoding="utf-8")

    assert "'sources' = 'Sources'" in builder
    assert (
        "(Project ID|Title|Word|Expected minutes|Script|Description|Tags|Sources|Storyboard)"
        in builder
    )


def test_windows_creative_builder_accepts_flow_image_id_suffixes():
    builder = Path("creative_work.ps1").read_text(encoding="utf-8")

    assert r"(?:_\d{14}|_[a-f0-9]{8})?" in builder
    assert r"(?:_\d{14}|_[a-f0-9]{8})$" in builder


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


def test_workflow_avoids_apt_and_verifies_ffmpeg_download():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    ffmpeg_action = Path(".github/actions/setup-ffmpeg/action.yml").read_text(
        encoding="utf-8"
    )

    assert "sudo apt-get" not in workflow
    assert workflow.count("uses: ./.github/actions/setup-ffmpeg") == 2
    approval_workflow = Path(
        ".github/workflows/ritzz-creative-approval-upload.yml"
    ).read_text(encoding="utf-8")
    assert approval_workflow.count("uses: ./.github/actions/setup-ffmpeg") == 1
    assert "command -v ffmpeg" not in workflow
    assert "command -v ffprobe" not in workflow
    assert (
        'release_url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"'
        in ffmpeg_action
    )
    assert 'archive_name="ffmpeg-master-latest-linux64-gpl.tar.xz"' in ffmpeg_action
    assert '"$release_url/checksums.sha256"' in ffmpeg_action
    assert ffmpeg_action.count("--retry 5 --retry-max-time 300") == 2
    assert 'awk -v filename="$archive_name"' in ffmpeg_action
    assert "sha256sum --check --status" in ffmpeg_action
    assert 'echo "$install_dir/bin" >> "$GITHUB_PATH"' in ffmpeg_action
    assert 'echo "RITZZ_FFPROBE_PATH=$install_dir/bin/ffprobe"' in ffmpeg_action
    assert '"$install_dir/bin/ffmpeg" -version' in ffmpeg_action
    assert '"$install_dir/bin/ffprobe" -version' in ffmpeg_action
    assert "google/fonts/45e3d5269e4a17d823f6d84470bc084dc5ae46f6" in workflow
    assert "ComicNeue-Bold.ttf" in workflow
    assert 'RITZZ_FONT_PATH=$RUNNER_TEMP/ritzz-fonts/ComicNeue-Bold.ttf' in workflow


def test_chatterbox_requirements_pin_perth_source_with_watermarker():
    requirements = Path("requirements-chatterbox.txt").read_text(encoding="utf-8")

    assert (
        "resemble-perth @ git+https://github.com/resemble-ai/Perth.git@"
        "ff1c8ac55a976971245cdd53c18d6131ca00d993"
    ) in requirements


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
    approval_workflow = Path(
        ".github/workflows/ritzz-creative-approval-upload.yml"
    ).read_text(encoding="utf-8")

    assert '-name "${PROJECT_ID}_*"' in workflow
    assert '-name "$PROJECT_ID_*"' not in workflow
    assert '-name "${RITZZ_PROJECT_ID}_*"' in approval_workflow
    assert '-name "$RITZZ_PROJECT_ID_*"' not in approval_workflow


def test_checkpoint_uploads_include_hidden_artifact_directory_files():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("uses: actions/upload-artifact@v4") == 2
    assert workflow.count("include-hidden-files: true") == 1


def test_preapproval_review_artifact_contains_only_the_rendered_mp4():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    production = workflow
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


def test_manual_upload_downloads_checkpoint_from_the_reviewed_source_run():
    workflow = Path(
        ".github/workflows/ritzz-creative-approval-upload.yml"
    ).read_text(encoding="utf-8")
    download_step = workflow.split(
        "      - name: Download approved production checkpoint\n", 1
    )[1].split("      - name: Restore reviewed project\n", 1)[0]
    resume_download_step = workflow.split(
        "      - name: Download approved production checkpoint\n", 1
    )[1].split("      - name: Restore reviewed project\n", 1)[0]

    assert "uses: actions/download-artifact@v4" in download_step
    assert "run-id: ${{ inputs.source_run_id }}" in download_step
    assert "github-token: ${{ github.token }}" in download_step


def test_private_upload_requires_owner_dispatch_and_explicit_review_approval():
    workflow = Path(
        ".github/workflows/ritzz-creative-approval-upload.yml"
    ).read_text(encoding="utf-8")
    production = WORKFLOW.read_text(encoding="utf-8")

    assert "approve_private_upload:" in workflow
    assert "default: false" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert '"$production_v2_workflow"' in workflow
    assert ".path == $production_v2_workflow" in workflow
    assert "Source must be a successful main-branch creative production run" in workflow
    assert "RITZZ_HUMAN_APPROVED: \"true\"" in workflow
    assert "run_private_upload_stage.py" in workflow
    assert "upload_youtube_thumbnail.py" in workflow
    assert "run_private_upload_stage.py" not in production
    assert "upload_youtube_thumbnail.py" not in production


def test_approval_upload_provides_oauth_file_paths_to_upload_steps():
    workflow = Path(
        ".github/workflows/ritzz-creative-approval-upload.yml"
    ).read_text(encoding="utf-8")
    upload_step = workflow.split(
        "      - name: Upload the approved metadata and final video privately\n",
        1,
    )[1].split("\n      - name:", 1)[0]
    thumbnail_step = workflow.split(
        "      - name: Set the supplied thumbnail on the private video\n",
        1,
    )[1].split("\n      - name:", 1)[0]

    for step in (upload_step, thumbnail_step):
        assert "GOOGLE_CLIENT_SECRETS_FILE: ${{ runner.temp }}/youtube-client-secrets.json" in step
        assert "GOOGLE_TOKEN_FILE: ${{ runner.temp }}/youtube-token.json" in step


def test_private_upload_records_a_completion_marker_to_prevent_duplicate_uploads():
    workflow = Path(
        ".github/workflows/ritzz-creative-approval-upload.yml"
    ).read_text(encoding="utf-8")

    upload_video = workflow.index("run_private_upload_stage.py")
    record_marker = workflow.index("Record private upload completion marker")
    upload_marker = workflow.index("Upload private-upload completion marker")
    save_checkpoint = workflow.index("Save resumable approved checkpoint")
    set_thumbnail = workflow.index("upload_youtube_thumbnail.py")

    assert upload_video < record_marker < upload_marker < save_checkpoint < set_thumbnail
    assert "repository_artifacts=$(gh api --paginate --slurp" in workflow
    assert "A private upload was already recorded" in workflow


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


def test_optional_image_override_supports_multiple_scenes_only_for_render_resume():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "image_override_release_tag:" in workflow
    assert "image_override_scene_ids:" in workflow
    assert "scene_041,scene_042" in workflow
    assert "Validate optional image override inputs" in workflow
    assert "Download image override package" in workflow
    assert "Apply selected image-only overrides" in workflow
    assert "scripts/apply_creative_image_overrides.py" in workflow
    override_condition = (
        "inputs.mode == 'RESUME' && inputs.rerun_from_stage == 'RENDER' && "
        "inputs.image_override_release_tag != ''"
    )
    assert workflow.count(override_condition) == 2
    assert workflow.index("Restore saved project") < workflow.index(
        "Download image override package"
    )
    assert workflow.index("Download image override package") < workflow.index(
        "Apply selected image-only overrides"
    )
    assert workflow.index("Apply selected image-only overrides") < workflow.index(
        "Generate or reuse supplied-script narration"
    )
    assert "inputs.rerun_from_stage == 'STORYBOARD'" in workflow


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
