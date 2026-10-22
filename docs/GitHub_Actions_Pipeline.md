# GitHub Actions Pipeline

Normal production uses a human-created creative package and starts from the
GitHub Actions web interface. Claude prepares the script and storyboard
handoff; Gemini fills all scene prompts and provides four character-reference
prompts. Images are generated manually in Flow Agent in gated batches of 10,
with the thumbnail as a separate final batch. Flow MCP is used afterward only
to match saved prompts and rename scene tiles; images are downloaded manually.
The PowerShell package builder validates and releases the approved assets.
GitHub Actions then generates only the narration, aligns the supplied
storyboard to the real narration timestamps, renders and technically checks
the video, waits for human approval, packages the approved inputs, and uploads
privately to YouTube.

## Primary workflow: Flow creative package

Workflow file: `.github/workflows/ritzz-creative-production.yml`

### Prepare and release the input

1. Use the current master prompt at
   `D:\AIStudio\Projects\Ritzz\Default\Ritzz_4_Master_Prompts\Ritzz_Single_Topic_Content_Master_Prompt.txt`.
   Claude creates the script and storyboard handoff; Gemini returns the
   complete final brief with four character references and every scene prompt.
   Do not use the legacy one-stage prompt in `prompts/flow` for new projects.
2. Open a dedicated Flow project for the video. In Flow Agent, generate only
   the four reference images first, titled `901`–`904`, and use them as
   references for each scene batch. Generate scenes in batches of exactly 10
   (the last may be smaller); wait until the queue is empty and every image is
   saved before continuing. Retry only failed slots. Generate the thumbnail
   separately after all scenes, titled `999`. Use raw global numbers as scene
   titles. Do not use MCP to generate, retry, or download images.
3. After all images exist, run
   `Generate RITZZ Images.cmd --rename-only` from the Flow MCP folder. It reads
   saved prompts, matches and renames scene tiles, and does not generate or
   download images. Manually download the scene images and thumbnail into a
   clean creative-package input folder; do not include the four reference
   images. Keep the final `_FlowReady.txt` brief with the staged inputs.
4. Review the downloaded images and thumbnail, then run `creative_package.bat`
   with the input folder path, for example:

   ```powershell
   .\creative_package.bat "projects\flow_staging\<generated-run-folder>"
   ```

   If you double-click the batch file without an argument, it asks for the
   staging folder path.
   The builder asks for the project ID and verifies that it matches the brief;
   a blank response stops before packaging. This step is separate from image
   generation so you can review before packaging or publishing. The script checks the supplied
   title, description, tag character count, script duration, storyboard
   coverage/order, thumbnail, and exact scene-image count; it converts scene
   images to 1536×864 PNG and the thumbnail to 1280×720 PNG. Timestamp suffixes
   on Flow downloads (for example, `scene_001_YYYYMMDDhhmmss.jpg` and
   `999_thumbnail_YYYYMMDDhhmmss.jpg`) are ignored for matching. The builder
   maps scenes by their numeric IDs, requires a complete ordered sequence, and
   renames files in the staging folder to `scene_NNN.jpg` and
   `999_thumbnail.jpg` (preserving image contents and extensions). It then
   writes renderer-ready `images/scene_NNN.png` files plus the project's named
   thumbnail PNG. Already-normalized names are left unchanged. It writes the
   project's files, creates `creative-package.zip`, validates it with the same
   Python importer used by Actions, and creates a GitHub release whose tag is
   exactly the project ID. The asset name is `creative-package.zip`.

Creative-package scripts are checked against 156 spoken words per minute
(1,404 words for a nine-minute minimum). Imported Flow scenes use actual
narration alignment and a strict eight-second maximum hold; longer holds should
target about six seconds. Resumed creative packages are updated to the
eight-second ceiling when the storyboard stage is rerun. The master prompt
targets image changes every two to three seconds, starts a new image at each
beat, and keeps the image cut on a meaningful narration boundary.

The Windows launchers and scripts are versioned in the repository:
`creative_package.bat`, `creative_work.bat` / `creative_work.ps1`,
`delete_workflow.bat` / `delete_workflow.ps1`, and
`new_ritzz_project.bat` / `New-RitzzProject.ps1`. They default to the sibling
`Projects\Ritzz` output directory when this repository is checked out under
`D:\AIStudio`; the PowerShell scripts also accept explicit root parameters for
another checkout. `projects/flow_staging` is ignored by Git so generated briefs
and images stay local.

To remove one project's local folder, GitHub release/tag, and matching Actions
runs/artifacts, run `delete_workflow.bat <PROJECT_ID>`. The script asks for the
exact confirmation phrase before deletion; `-WhatIf` can be passed to inspect
the targets without deleting them.

The rename-only launcher requires a final Flow-ready brief and saved prompts in
the open Flow project. Use a dedicated project to avoid unrelated tiles.
Download scene files with their global scene numbers in the filename and name
the thumbnail `thumbnail` while preserving its actual extension (for example,
`thumbnail.jpg`). The creative-package step converts them to
`images/scene_001.png` and the required `thumbnail.png` output. The package
builder checks file integrity and dimensions; it does not claim visual content
is correct.

### Run, review, and upload

In **Actions → RITZZ Creative Package Production → Run workflow**, select
`mode=NEW` and enter the project ID in `creative_package_release_tag`. The
workflow validates the ZIP before making a paid voice API call. No OpenAI,
Replicate, research, storyboard-planning, image-generation, or thumbnail-
generation API is called in Actions.

The supplied script is narrated with the configured RITZZ ElevenLabs voice
(`eleven_multilingual_v2`, speed `0.92`, stability `0.90`, similarity boost
`0.75`, style exaggeration `0`, speaker boost enabled). Scene starts are mapped
to actual ElevenLabs character timestamps. The workflow validates scene/image
coverage, uses static stills and hard cuts, then renders and runs technical
video QA. A technical failure blocks approval. The rendered video is the human
check for image/narration relevance and image quality.

The `0.92` speed is a configurable production default calibrated against
measured narration pacing; the requested minimum duration remains a hard gate.
If narration is still short, the error reports its measured words-per-minute
rate and the approximate word count needed at that pace. Audio is never stretched.

At workflow dispatch, select `Ritzz-Explains`, `RitzzHistory`, or `RitzzTech1`.
The selected channel is shown in the review summary and controls which
channel-specific OAuth token is used for upload. The upload stage verifies the
token's authenticated channel title before it creates approval state or uploads
anything; it also checks YouTube's returned channel ID after upload.

Before pausing at the protected `ritzz-packaging-approval` environment, the
production job publishes a separate `ritzz-review-video-<project-id>` artifact
containing only the rendered MP4, in addition to the complete final review ZIP.
Download the MP4-only artifact and extract its MP4 into your local Downloads
folder for review. GitHub Actions artifacts are delivered as ZIP files; the
cloud runner cannot write directly to a reviewer's PC. To download and extract
only that MP4 directly into Downloads, use the PowerShell command shown in the
workflow summary (GitHub CLI must be authenticated):

```powershell
gh run download <run-id> --repo sakshatshetty/RitzzStudio --name "ritzz-review-video-<project-id>" --dir "$env:USERPROFILE\Downloads"
```

A trusted reviewer watches the video and approves or rejects the job. After
approval, the workflow revalidates the exact supplied title, description, tags,
and thumbnail, builds the approved final package, and uploads the video
privately with the supplied metadata. It creates a separate
`thumbnail/processed_thumbnail.png` using the same Gemini spot-reduction mask
as the renderer and uploads that copy as the YouTube thumbnail; the supplied
source image remains unchanged. Public visibility is not enabled.

The creative ZIP root must contain `project.json`, the five named metadata/
thumbnail assets, the storyboard JSON, and every PNG referenced in
`image_files`. Example:

```json
{
  "project_id": "20261007_001",
  "topic": "Why Do Pirates Wear Eye Patches?",
  "target_duration_minutes": 8,
  "script_file": "script.txt",
  "title_file": "title.txt",
  "description_file": "description.txt",
  "tags_file": "tags.txt",
  "thumbnail_file": "thumbnail.png",
  "storyboard_file": "storyboard.json",
  "image_files": [
    "images/scene_001.png",
    "images/scene_002.png"
  ]
}
```

Storyboard scene excerpts must reproduce the supplied script exactly in order
when normalized for whitespace and punctuation. Each image is a readable
RGB/RGBA 1536×864 PNG named for its scene ID. The thumbnail must be a readable
RGB/RGBA PNG, at least 1280×720 and 16:9 (allowing one-pixel rounding). The
storyboard supports at most 200 scenes, and the release ZIP is limited to
250 MiB. Image semantic relevance remains a human-review responsibility.

### Resume a production

Choose `mode=RESUME`, and provide the project ID and source Actions run ID with
an unexpired checkpoint:

- `CONTINUE` reuses the completed voice, aligned storyboard, and render stages.
- `NARRATION` generates narration again, retimes the supplied storyboard, and
  rerenders.
- `STORYBOARD` reuses narration, retimes the supplied scenes, and rerenders.
- `RENDER` reuses the voice and timed storyboard and rerenders.
- `FINAL_PACKAGE` reuses the saved render and recreates the final review ZIP.

Changing the creative files requires creating a new project ID and release.
Reruns preserve the accepted input package and do not regenerate Flow images.
The protected approval environment remains in force for runs that proceed to
upload.

## Legacy generated-creative workflow

Workflow file: `.github/workflows/ritzz-pipeline.yml` (named
“RITZZ Legacy Generated-Creative Pipeline” in Actions)

This workflow is retained for compatibility with existing checkpoints. It
still performs the former generated-creative flow described below; do not use
it for new user-supplied ZIP productions.

When starting a run, the GitHub form provides `Discovery mode`, `Test run`,
`Target video duration in minutes`, and `Minimum allowed video duration in
minutes`, `Project ID`, and `Rerun from stage`. Both duration fields default to
8 minutes, and the minimum cannot exceed the target. Leave `Rerun from stage` at
`new_run` for a new production. To resume an existing project, enter its exact
project ID and select the stage to retry; the workflow restores the latest
unexpired saved archive from the immediately preceding stage and skips topic
discovery and content creation.

Project reruns are supported from `voice_generation`, `storyboard_generation`,
`image_generation`, `render_video`, `metadata_packaging`,
`thumbnail_packaging`, and `private_upload`.
For example, choosing `render_video` restores the project's latest saved
image-stage archive, then runs rendering, video review, final metadata
packaging, packaging review, and (after approval) private upload. Failed
upstream stages are not silently repeated. The selected stage
must have its required preceding-stage artifact available in an unexpired
Actions artifact. Video and packaging approval environments remain in force
for reruns that reach those steps.

If image generation fails, the workflow also archives the partial image
manifest and project before marking the stage failed. Resuming at image
generation restores that archive and reuses only completed PNGs whose scene,
provider, prompt, and dimensions still match; missing, corrupt, stale, and
failed images are generated again. Progress is saved after each scene, so a
later provider failure does not discard earlier completed images.
For failures from runs made before partial image checkpoints were added, resume
falls back to the saved storyboard project and starts image generation from the
first scene.

Before tests or external providers run, the workflow validates that all required
secrets are present and that the Google client and token secrets decode to valid
OAuth JSON. This preflight makes no provider API calls, so it does not consume
quota or prove that a key has live service permission; provider failures still
stop their individual stage.

1. Run focused pipeline regression tests.
2. Research the configured format competitors for channel-relative outlier videos.
3. Generate original RITZZ ideas from those outliers and validate them with vidIQ.
4. Publish 3–5 qualified candidates in a GitHub issue and workflow artifact.
5. Wait for a trusted collaborator to select one of the candidate numbers.
6. Pause at the protected topic-approval environment.
7. Pause at the protected test-approval environment.
8. Run the existing Research -> Outline -> Script content workflow.
9. Upload the generated project artifacts to the GitHub Actions run.
10. Persist approved topic, competitor provenance, and cached vidIQ evidence with the project.
11. Generate and validate ElevenLabs narration with character alignment.
12. Build the narrative and audio-timed static storyboard.
13. Render the test video and complete applicable technical and semantic QA.
14. Pause for human video review and approval.
15. Generate final title, description, and tags from the completed production;
    reuse cached vidIQ evidence and save `metadata_packaging.json`.
16. Generate 3–5 original thumbnail concepts; a trusted collaborator selects
    one before a single clean artwork image is generated and exact hook text is
    composited with FFmpeg.
17. Run deterministic thumbnail checks and show the preview, clean artwork,
    selected concept, and review status before final packaging approval.
18. Upload the test video privately through YouTube OAuth after approval.
19. Keep the current run marked as a test run; public publication remains
   disabled.

Metadata packaging is resumable independently. A completed metadata artifact is
reused without another GPT or vidIQ call; a failed metadata stage can be retried
without rerunning discovery, topic selection, or media generation. Thumbnail
packaging is a separate resumable stage: it reuses completed concepts and
artwork, and retries do not repeat video production or metadata generation.
OpenAI generates concepts and only the human-selected concept's artwork.
FFmpeg adds the exact approved uppercase hook to a dedicated 1280×720 image;
the original clean artwork is also saved for visual review. Image-model text
cannot be proven absent mechanically, so the final human approval includes a
visual check of the clean art and thumbnail preview. Thumbnail concept QA
rejects a small or distant focal subject only when its composition does not
explicitly make it prominent, such as with a close-up or foreground framing.

Topic duplicate prevention reads the durable repository inventory at
`data/content_inventory.json`. Test runs do not write to this file and therefore
do not reserve or permanently exclude their selected topics. A future approved
V1 release will update the inventory with the final topic and publication data.

Topic discovery uses the configured competitor registry as its source of truth.
It compares successful videos against each channel's own baseline when enough
videos are returned, uses provider breakout scores when supplied, and retains
the source, channel, video, observed views, baseline/multiple, publication age,
and collection time when available. GPT generates original topic ideas from
that evidence; vidIQ keyword research validates those ideas, not a separate
trending/evergreen fallback pool. The workflow does not call unscoped trending,
rising, broader-trending, or long-tail fallbacks. It stops before approval if
fewer than two strong candidates pass inventory, editorial, and vidIQ checks.
The collaborator still chooses the topic; no highest-score candidate is
selected automatically.

## Repository setup

The primary Flow-package workflow needs these secrets:

- `ELEVENLABS_API_KEY`
- `RITZZ_VOICE_ID`
- `GOOGLE_CLIENT_SECRETS_B64`
- `GOOGLE_TOKEN_B64` for `Ritzz-Explains` (`@Ritzz-Explains`)
- `GOOGLE_TOKEN_RITZZ_HISTORY_B64` for `RitzzHistory` (`@RitzzHistory`)
- `GOOGLE_TOKEN_RITZZ_TECH_B64` for `RitzzTech1` (`@RitzzTech1`)

Create a separate OAuth token for each channel by authorizing the YouTube API
client while the corresponding channel is selected, then store each token file
as Base64 JSON in its named GitHub Actions secret. The existing
`GOOGLE_TOKEN_B64` remains the token for `Ritzz-Explains`. All three tokens
require the YouTube upload and read-only scopes. Selecting a channel whose
secret is missing fails during prerequisite validation, before production
starts.

The legacy generated-creative workflow still uses `OPENAI_API_KEY`,
`VIDIQ_MCP_API_KEY`, and any image-provider credentials it requires. Those
secrets are not passed to the primary Flow-package workflow.

The OAuth token must include both YouTube upload and read-only scopes so the
pipeline can verify the selected channel and perform one non-blocking
processing-status check after upload. To create a token for a channel, set
`GOOGLE_TOKEN_FILE` to a unique path, select that channel during OAuth, and run
`scripts/authorize_youtube.py`. Set `RITZZ_YOUTUBE_CHANNEL_TITLE` to its exact
channel title and run `scripts/verify_youtube_channel.py` before storing the
Base64 token as the matching Actions secret. Never reuse one channel's token
secret for another selection.

If channel verification fails with `invalid_grant`, Google has rejected the
stored refresh token because it expired or was revoked. Reauthorize that
channel with `scripts/authorize_youtube.py`, verify the new token with
`scripts/verify_youtube_channel.py`, Base64-encode the resulting token JSON, and
replace only that channel's Actions secret. Do not put token contents in source
control or workflow logs.

The `RITZZ_VIDEO_BITRATE` Actions variable is optional and defaults to `10M`.
The render and upload jobs use the same value; the upload gate rejects targets
or measured masters outside 8–12 Mbps.

Create the protected environment for the primary Flow-package workflow and
require trusted reviewers:

- `ritzz-packaging-approval`

The legacy generated-creative workflow uses these additional environments:

- `ritzz-topic-approval`
- `ritzz-test-approval`
- `ritzz-video-approval`

The legacy workflow requires issue write permission so it can create the topic
approval issue. Only trusted repository collaborators should reply to that
issue.

## Test-video rule

M8 and M9 runs are test runs. Generated or uploaded test videos must remain
private or unlisted. Public publication is disabled until the complete pipeline
and approval flow have passed validation. V1 is the first actual public video.

## Next M8 slices

- Add final public-publication approval and the V1-only public release path.
- Add scheduled M7 analytics collection after a test upload.
