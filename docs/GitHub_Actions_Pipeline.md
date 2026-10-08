# GitHub Actions Pipeline

RITZZ video runs are started from the GitHub Actions web interface. Normal video
production does not require a local command-line command.

## Primary workflow: user-supplied creative package

Workflow file: `.github/workflows/ritzz-creative-production.yml`

This is the normal production path. It does not discover/select a topic or
generate/rewrite the supplied script, title, description, tags, or thumbnail.
The ZIP is validated before research, ElevenLabs, or image-generation calls.
Production then researches factual visual context, generates narration from the
supplied script, aligns scenes to actual narration timestamps, plans visual
contracts with neighboring-scene context, generates images, runs deterministic
and targeted semantic QA, renders with static images and hard cuts, and creates
a final review ZIP. Uncertain semantic checks remain visible for human review;
clear failures and technical QA failures block progression.

The ZIP root must contain `project.json` and exactly the five files referenced
by it. Example manifest:

```json
{
  "project_id": "20261007_001",
  "topic": "Why Do Pirates Wear Eye Patches?",
  "target_duration_minutes": 8,
  "script_file": "script.txt",
  "title_file": "title.txt",
  "description_file": "description.txt",
  "tags_file": "tags.txt",
  "thumbnail_file": "thumbnail.png"
}
```

The script is UTF-8 text; title and description are UTF-8 text; `tags.txt` has
one non-empty, trimmed tag per line; and the thumbnail is a readable RGB/RGBA
PNG at 16:9 and at least 1280×720. The script is checked against the target
runtime before paid production calls. The ZIP importer preserves the source
files and refuses project-ID reuse with different content. Audio-timed holds
may vary from 1 to 6 seconds, with hold reason, visual weight, narration
density, and cut-boundary context recorded for QA. Camera movement and
transitions remain disabled.

To provide the ZIP without a separate hosting service, upload it as a GitHub
release asset:

1. Open the repository's **Releases** page and choose **Draft a new release**.
2. Enter a new release tag (for example, `creative-20261007-01`).
3. Attach the ZIP and name the asset exactly `creative-package.zip`.
4. Publish the release. The repository can remain private; the workflow uses
   its read-only GitHub token to download the asset.
5. In **Actions → RITZZ Creative Package Production → Run workflow**, choose
   `mode=NEW` and enter the release tag in `creative_package_release_tag`.

The ZIP must be no larger than 250 MiB. No package-host variable or download
token secret is required. Configure the existing `ritzz-packaging-approval`
environment with trusted reviewers. The final review job runs only after
protected approval; it uploads the exact supplied title, description, tags, and
thumbnail with the technically validated video. YouTube visibility remains
private.

To resume, choose `mode=RESUME` and provide the project ID plus the Actions run
ID that contains its checkpoint. A resume requires an unexpired checkpoint
artifact. Completed voice/storyboard assets are validated and reused, and
completed images are resumed from their manifest.

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

Configure these GitHub repository secrets:

- `OPENAI_API_KEY`
- `VIDIQ_MCP_API_KEY`
- `ELEVENLABS_API_KEY`
- `RITZZ_VOICE_ID`
- `GOOGLE_CLIENT_SECRETS_B64`
- `GOOGLE_TOKEN_B64`

The OAuth token must include both YouTube upload and read-only scopes so the
pipeline can perform one non-blocking processing-status check after upload.
If the token was authorized before this change, reauthorize it with
`scripts/authorize_youtube.py` and update `GOOGLE_TOKEN_B64`.

The `RITZZ_VIDEO_BITRATE` Actions variable is optional and defaults to `10M`.
The render and upload jobs use the same value; the upload gate rejects targets
or measured masters outside 8–12 Mbps.

Create these GitHub environments and require reviewers for each environment:

- `ritzz-topic-approval`
- `ritzz-test-approval`
- `ritzz-video-approval`
- `ritzz-packaging-approval`

The workflow requires issue write permission so it can create the topic approval
issue. Only trusted repository collaborators should reply to that issue.

## Test-video rule

M8 and M9 runs are test runs. Generated or uploaded test videos must remain
private or unlisted. Public publication is disabled until the complete pipeline
and approval flow have passed validation. V1 is the first actual public video.

## Next M8 slices

- Add final public-publication approval and the V1-only public release path.
- Add scheduled M7 analytics collection after a test upload.
