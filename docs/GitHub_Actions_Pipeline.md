# GitHub Actions Pipeline

Normal production uses a human-created creative package and starts from the
GitHub Actions web interface. ChatGPT or Claude prepares the script, metadata,
Flow-ready storyboard prompts, and thumbnail prompt. A local Flow MCP launcher
reads the single brief in the input folder, generates the scenes in Agent
batches, generates the thumbnail, and stages the files for human review. The
PowerShell package builder validates and releases the approved assets. GitHub
Actions then generates only the narration, aligns the supplied storyboard to
the real narration timestamps, renders and technically checks the video, waits
for human approval, packages the approved inputs, and uploads privately to
YouTube.

## Primary workflow: Flow creative package

Workflow file: `.github/workflows/ritzz-creative-production.yml`

### Prepare and release the input

1. Paste the prompt from
   `D:\AIStudio\Projects\Ritzz\Default\Ritzz_4_Master_Prompts\Ritzz_Single_Topic_Content_Master_Prompt.txt`
   into ChatGPT or Claude with the project ID, topic, target duration, and word
   count. It returns one text file containing the supplied metadata and a
   machine-readable storyboard. Each scene includes an exact narration excerpt,
   a visual description, a self-contained Flow image prompt, and a canonical
   image filename.
2. Put the brief in
   `D:\AIStudio\Projects\Ritzz\Default\Ritzz_4_Master_Prompts\temp`. Keep
   exactly one `.txt` creative brief in that folder. Ensure the Flow MCP Chrome
   session is signed in and has a Flow project open, then double-click
   `D:\AIStudio\flow-mcp\Generate RITZZ Images.cmd`. It reads the brief without
   a file picker, generates scene prompts in batches of up to 50, generates
   the thumbnail separately, downloads the results, and stages them beside a
   copy of the brief in a new project-specific subfolder under `temp`. The
   staging folder is printed when generation completes. Legacy stickman-style
   prompts are upgraded to detailed storybook/editorial-cartoon prompts in the
   staged copy; the source brief is left unchanged. A running Flow MCP job
   blocks a new run; wait for it to finish instead of launching another batch.
3. Review every staged image and thumbnail. The generator reports Flow's
   measured credit change when available. Flow Agent has reported zero credit
   use in prior runs, but Google can change quotas and limits; do not treat
   zero-cost generation as guaranteed. A failed or incomplete batch is not
   presented as ready for packaging.
4. Run `creative_work.bat` with the staging folder path, for example:

   ```powershell
   .\creative_work.bat -InputDirectory "D:\AIStudio\Projects\Ritzz\Default\Ritzz_4_Master_Prompts\temp\<generated-run-folder>"
   ```

   This step is separate from image generation so you can review before
   packaging or publishing. The script checks the supplied
   title, description, tag character count, script duration, storyboard
   coverage/order, thumbnail, and exact scene-image count; it converts scene
   images to 1536×864 PNG and the thumbnail to 1280×720 PNG. It writes the
   project's files, creates `creative-package.zip`, validates it with the same
   Python importer used by Actions, and creates a GitHub release whose tag is
   exactly the project ID. The asset name is `creative-package.zip`.

Flow MCP's Agent image-batch tool accepts up to 50 prompts per call. The
launcher splits larger storyboards automatically and stages scene images as
`scene_001.jpeg`, `scene_002.jpeg`, and so on, with `thumbnail.jpeg` for the
thumbnail. Review generated assets manually. The package builder checks file
integrity and dimensions; it does not claim visual content is correct.

### Run, review, and upload

In **Actions → RITZZ Creative Package Production → Run workflow**, select
`mode=NEW` and enter the project ID in `creative_package_release_tag`. The
workflow validates the ZIP before making a paid voice API call. No OpenAI,
Replicate, research, storyboard-planning, image-generation, or thumbnail-
generation API is called in Actions.

The supplied script is narrated with the configured RITZZ ElevenLabs voice
(`eleven_multilingual_v2`, speed `1.0`, stability `0.90`, similarity boost
`0.75`, style exaggeration `0`, speaker boost enabled). Scene starts are mapped
to actual ElevenLabs character timestamps. The workflow validates scene/image
coverage, uses static stills and hard cuts, then renders and runs technical
video QA. A technical failure blocks approval. The rendered video is the human
check for image/narration relevance and image quality.

The production job publishes the downloadable final review ZIP and pauses at
the protected `ritzz-packaging-approval` environment. A trusted reviewer
watches the video and approves or rejects the job. After approval, the workflow
revalidates the exact supplied title, description, tags, and thumbnail, builds
the approved final package, and uploads the video privately with the supplied
metadata and thumbnail. Public visibility is not enabled.

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
- `GOOGLE_TOKEN_B64`

The legacy generated-creative workflow still uses `OPENAI_API_KEY`,
`VIDIQ_MCP_API_KEY`, and any image-provider credentials it requires. Those
secrets are not passed to the primary Flow-package workflow.

The OAuth token must include both YouTube upload and read-only scopes so the
pipeline can perform one non-blocking processing-status check after upload.
If the token was authorized before this change, reauthorize it with
`scripts/authorize_youtube.py` and update `GOOGLE_TOKEN_B64`.

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
