# RITZZ Master Milestones

**Project:** RITZZ Studio
**Channel:** One faceless English-language YouTube channel
**Niche:** Mixed Curiosity
**Status source:** This document records the long-term roadmap. `milestone.md` records the current verified checkpoint.
**Last updated:** 2026-09-26
**Change log:** [CHANGELOG.md](../CHANGELOG.md)

## Eventual Goal

Build an automated, resumable CI/CD content-production pipeline for one RITZZ YouTube channel:

```text
Topic intelligence
  -> Human topic approval
  -> Research and fact validation
  -> Outline
  -> Script
  -> Storyboard
  -> Narration
  -> Audio-timed scenes
  -> Image generation
  -> Asset QA
  -> Video rendering
  -> Technical and semantic QA
  -> Human final approval
  -> Titles, thumbnail, and metadata
  -> YouTube upload and scheduling
  -> Inventory and analytics learning loop
```

The pipeline must preserve intermediate artifacts, support retry and resume, keep human approval explicit, and avoid regenerating expensive assets unnecessarily.

## Production Rules

- One channel only. Do not add multi-channel architecture.
- General audience, English language, curious and easy-to-understand tone.
- No recurring narrator personality or recurring host.
- Simple 2D stickman/cartoon visual style.
- Flat colors, thick black outlines, minimal shading.
- Static images only.
- No camera movement, pan, zoom, or transitions.
- Hard cuts only.
- Scene duration is driven by narration timing and visual context.
- Aim for approximately three seconds per image where the narrative supports it.
- Editorial callouts are embedded in images, not subtitles.
- Editorial callouts are exactly one uppercase word and maximum 20 characters.
- Video target duration and minimum allowed duration are configurable. During topic approval, the user selects both values; the current default target remains approximately eight minutes.
- The eight-minute value is the current backward-compatible baseline inherited from the existing Outline and Script engines, not a permanent product restriction. Full user-selected duration propagation is completed in M3.
- Publishing cadence is configurable; the current target is Tuesday and Saturday.
- Use the configured RITZZ ElevenLabs voice, OpenAI image generation, and FFmpeg rendering.

## Milestone Status

| Milestone | Area | Status |
| --- | --- | --- |
| M0 | Repository foundation and core engines | Substantially complete |
| M1 | Topic decision system and content inventory | Complete for current scope |
| M2 | Research validation and fact checking | Complete for current scope |
| M3 | Configurable content brain | Complete for current scope |
| M4 | Resumable end-to-end production orchestration | Complete for current scope |
| M5 | Packaging: titles, thumbnails, and metadata | Complete for current scope |
| M6 | YouTube publishing and scheduling | Offline/provider scope complete; live OAuth verification pending |
| M7 | Inventory completion and analytics learning loop | Planned |

A milestone is complete only when its acceptance criteria, focused tests, artifacts, and human approval requirements are satisfied.

## M0 - Foundation and Existing Production Engines

### Completed or substantially implemented

- Project manager and project directory structure.
- Research Engine with structured research and source references.
- Outline Engine with duration validation.
- Script Engine with duration validation and expansion retries.
- Conventional and dynamic storyboard engines.
- Editorial text planning and one-word callout rules.
- ElevenLabs provider, voice settings, audio generation, and character alignment.
- Audio-timed storyboard grouping.
- Image prompt and image generation pipeline.
- Video assembly and synchronization.
- Static FFmpeg rendering with hard cuts.
- Technical video QA.
- Semantic QA framework with PASS, REVIEW, and FAIL states.
- Content workflow for Research -> Outline -> Script.
- Intermediate JSON artifacts and cache behavior.

### Current pilot evidence

Project: `20260820_001_why_do_pirates_wear_eye_patches`

- Revised pilot render exists in `pilot_3min/revision_v2`.
- Revised audio-timed storyboard contains 54 scenes.
- Dedicated audio is approximately 225 seconds.
- 54 audio-timed images were generated.
- The pilot confirms the intended order: narration audio and character timestamps are generated first, then scene timing is derived from the audio, then images are generated for those timed scenes.
- Technical QA is PASS.
- The current `pilot_3min/revision_v2` technical QA report is PASS for all 54 scenes: audio is 225.326440 seconds, rendered video is 225.333333 seconds, duration difference is 0.006893 seconds, and maximum timeline drift is zero.
- Semantic QA remains REVIEW: local visual review covered 14 editorial frames, but complete narration-to-image review is unfinished. The existing review artifact says the external automated image/narration review was blocked by its approval reviewer.
- Opt-in OpenAI image/editorial review and a single targeted repair attempt are implemented in the production pipeline, but have not yet been run on this pilot. Review remains a cost-bearing step; any generated replacement preserves the original image for comparison.
- Full eight-minute production is not approved yet.

## M1 - Topic Decision System and Content Inventory

**Goal:** Select a strong, distinct RITZZ topic using evidence from vidIQ, competitor outliers, and the existing RITZZ content inventory.

### Deliverables

- Persistent content inventory containing:
  - Topic and normalized topic.
  - Keywords and covered concepts.
  - Project/video ID.
  - Status.
  - Creation and publication dates.
  - Final title and URL when published.
  - Related and near-duplicate topics.
- Exact duplicate checking.
- Semantic or near-duplicate checking.
- vidIQ trending and increasing-demand discovery.
- Competitor/outlier research using supported vidIQ tools.
- Evergreen and long-tail discovery path.
- Combined opportunity evaluation using:
  - Demand and search volume.
  - Trend momentum.
  - Competition.
  - Existing saturation.
  - RITZZ niche fit.
  - Curiosity strength.
  - Evergreen potential.
  - English/general-audience potential.
  - Visual storytelling potential.
  - Researchability.
  - Differentiation.
- Exactly four distinct candidate ideas per approved discovery request.
- Every candidate includes:
  - Topic.
  - Proposed title or angle.
  - Why it is interesting.
  - Demand/trend evidence.
  - Competition evidence.
  - Opportunity score and completeness.
  - RITZZ fit.
  - Visual potential.
  - Trending/evergreen classification.
  - Differentiation angle.
- User selects target video duration and minimum allowed video duration.
- User supplies optional topic constraints or production instructions.
- User selects exactly one topic.
- Selected topic is locked in `topic_selection.json` before project creation.
- Project metadata links to the discovery report and inventory decision.

### Current implementation progress

- Persistent JSON inventory is implemented.
- Exact and near-duplicate topic checks are implemented.
- Discovery output is capped at four distinct candidates.
- Candidate title/angle fields are supported.
- Topic selection persists target duration, minimum duration, constraints, and lock time.
- Manual duplicate topics are blocked before project creation.
- Live discovery now attaches competitor/outlier evidence and applies niche-fit flags before recommendation gating.
- Remaining M1 work: human selects one of the four reviewed candidates and confirms duration/constraints in a real project artifact.

### Existing implementation to reuse

- `modules/topic_intelligence/`
- `modules/content_workflow/`
- `app.py`
- `cache/topic_intelligence/`
- `tests/test_topic_intelligence.py`
- `tests/test_content_workflow.py`

### Acceptance criteria

- No recommended candidate substantially overlaps an existing RITZZ topic unless explicitly allowed.
- Discovery returns exactly four distinct candidates.
- Missing provider signals remain missing and are visible.
- Competitor success is treated as evidence, not a guarantee.
- A human explicitly selects one candidate.
- Target duration, minimum duration, and constraints are saved with the selection.
- A selected topic can create or resume a project without losing provenance.
- Manual topic entry remains functional.

## M2 - Research Validation and Fact Checking

**Goal:** Prevent unsupported or contradictory claims from reaching the outline and script.

The first M2 implementation adds deterministic research validation between the
Research and Outline stages. It writes `research/research_validation.json` and
stops before outlining when a high-importance claim has no usable evidence.

### Deliverables

- Research validation artifact linked to `research.json`.
- Important-claim extraction.
- Source coverage validation for important claims.
- Unsupported-claim detection.
- Contradiction detection.
- Uncertainty and cautious-wording flags.
- Source quality and freshness reporting.
- Explicit PASS, REVIEW, and FAIL result.
- Pipeline stops before outline generation on FAIL.
- Human review remains possible for REVIEW.

### Current implementation progress

- Deterministic source-reference validation is implemented in `modules/research/validation.py`.
- High-importance claims without usable source evidence produce FAIL.
- Low-confidence claims produce REVIEW and cautious-wording guidance.
- Validation reports are saved to `research/research_validation.json`.
- The content workflow runs validation between Research and Outline when the research engine returns a validated `Research` object.
- Remaining M2 work: stronger claim extraction. Potential contradictions are conservatively flagged for REVIEW; they are not automatically resolved. Live validation has now been exercised against a real research artifact.

### Acceptance criteria

- Every high-importance claim has source references or is flagged.
- Conflicting interpretations are preserved rather than silently resolved.
- No unsupported claim is silently passed to scripting.
- Cached validation is invalidated when research changes.

## M3 - Configurable Content Brain

**Goal:** Make duration, tone, and constraints flow consistently through Research, Outline, Script, Voice, and Storyboard.

### Deliverables

- Project-level production configuration.
- Target duration and minimum duration.
- User-selectable target and minimum duration values captured during topic approval.
- Configurable words-per-minute or narration pacing reference.
- Configurable tone/style rules.
- Configurable scene duration minimum and maximum.
- Outline and script prompts use the project configuration.
- Voice minimum-duration gate uses the same configuration.
- Storyboard and timed-scene validation use the same configuration.
- Existing eight-minute defaults remain backward compatible.

### Current implementation progress

- `ProductionConfig` now stores target duration, minimum duration, pacing, scene limits, and constraints.
- Content workflow persists `production_config.json` and passes configuration to Outline and Script when supported.
- Outline prompts and validation use the selected target duration.
- Script prompts, minimum word validation, and generated metadata use the selected target/minimum duration.
- Existing engine doubles and older project metadata remain compatible.
- M3 scope is complete: Research, Outline, Script, Voice, static Storyboard, and audio-timed Storyboard honor `ProductionConfig` when called. A full workflow test proves a non-default duration reaches Research -> Outline -> Script.

### Acceptance criteria

- An eight-minute request behaves as it does today.
- A different approved duration propagates through every downstream stage.
- Duration mismatches stop the pipeline with an actionable error.
- Configuration is saved as a project artifact.

## M4 - Resumable End-to-End Production Orchestrator

**Goal:** Run the selected topic through all production stages with resumable, idempotent stage state.

### Deliverables

- Unified orchestration from approved topic to QA report.
- Explicit stage states: pending, running, completed, review, failed.
- Stage logs and timestamps.
- Retry from the failed stage.
- Cache reuse for completed stages.
- No regeneration of valid audio or images unless explicitly forced.
- Audio and image asset validation before rendering.
- Character and visual continuity checks.
- Static camera and hard-cut enforcement.
- Cost and usage records for paid provider calls.

### Current implementation progress

- `pipeline_state.json` persists assembly, synchronization, motion, and render stage status with timestamps and errors.
- Existing plan artifacts are reused when `VideoProductionRequest.resume` is enabled.
- Image and audio assets are validated before plan construction and rendering.
- Corrupt or missing PNG assets stop the pipeline before rendering.
- Post-render technical QA is now executed and stored in the production result; human approval remains explicitly `PENDING`.
- Stage failures are recorded against the active stage instead of a generic pipeline failure.
- M4 scope is complete: cost/usage timing records, explicit retry-from-stage control, stage-specific failure persistence, asset validation, technical QA, and pending human approval are implemented and tested.
- Provider-specific monetary pricing is intentionally not invented; `pipeline_usage.json` records stage attempts, elapsed time, and errors. Paid-provider cost fields can be added when provider billing metadata is available.

### Acceptance criteria

- A failed stage preserves all previous valid artifacts.
- Rerunning resumes at the failed or requested stage.
- Rendering cannot start with missing or corrupt assets.
- Technical QA must PASS before human final approval.
- Semantic QA issues are classified PASS, REVIEW, or FAIL without automatic deletion.

## M5 - Packaging: Titles, Thumbnails, and Metadata

**Goal:** Produce accurate, competitive packaging without copying competitors.

### Deliverables

- vidIQ title and thumbnail research.
- Competing title and keyword evidence.
- Title options with rationale.
- User or configured workflow selects the final title.
- RITZZ thumbnail generation.
- Thumbnail readability and mobile-visibility validation.
- Description, keywords/tags, category, and configured metadata.
- Metadata accuracy checks against the approved script/topic.

### Acceptance criteria

- Final title accurately represents the video.
- Thumbnail is readable at mobile size.
- Packaging is not misleading.
- Competitor patterns inform but do not duplicate another creator's work.
- Packaging artifacts are linked to the project.

### Current status

M5 is complete for the current scope. Packaging is integrated into the content
workflow and persists title options, selected title, thumbnail brief, and
metadata. Focused packaging and workflow tests pass.

## M6 - YouTube Publishing and Scheduling

**Goal:** Upload and schedule only after explicit human approval.

### Deliverables

- YouTube provider abstraction.
- Upload final video and thumbnail.
- Apply title, description, and metadata.
- Configurable publishing schedule.
- User schedule override.
- Upload retry behavior.
- Publish verification.
- Stored YouTube video ID, URL, title, and publish status.

### Acceptance criteria

- No upload occurs without an approval artifact.
- Upload failure preserves all local assets and supports retry.
- Successful publishing stores the YouTube identifiers and schedule.
- Credentials remain outside source code.

### Current status

The offline/provider contract is complete and tested. Publishing now has
explicit approval and schedule artifacts, a project-level orchestration call,
result persistence, a fake provider for offline tests, and an opt-in OAuth
`YouTubeProvider` with scheduled `publishAt` support. The focused publishing
tests pass and the full offline suite passes 325 tests with one live test
deselected.

The project-level publish orchestration now requires an approved artifact
created as a separate step and verifies that the supplied approver matches the
saved approval identity. It cannot implicitly approve and publish in one call.
Focused publishing/provider tests pass (9).

Remaining M6 work is a controlled live upload verification. No Google OAuth
client-secret/token files or YouTube/Google OAuth environment variables are
currently configured, so no live upload was attempted. Configure credentials,
review and explicitly approve a final video and packaging, then verify the
stored YouTube video ID, URL, schedule, and publish status. Do not begin M7
analytics integration until that verification is complete.

## M7 - Inventory Completion and Analytics Learning Loop

**Goal:** Learn from published RITZZ performance without creating a second channel architecture.

### Deliverables

- Inventory update after successful publishing.
- Periodic analytics collection.
- Views, CTR, average view duration, retention, watch time, engagement, traffic sources, audience geography, and revenue/RPM where available.
- Analytics artifact linked to project and video ID.
- Topic performance aggregation.
- Feedback into opportunity scoring.
- Versioned scoring changes and explainable weight updates.

### Acceptance criteria

- Published topics cannot be recommended as duplicates.
- Analytics failures do not corrupt inventory or production artifacts.
- Learning changes are auditable and reversible.
- No single viral result automatically changes scoring weights.

## Cross-Cutting Engineering Requirements

Every new milestone must:

- Inspect actual files, callers, and tests before editing.
- Reuse existing interfaces where possible.
- Keep external services behind provider abstractions.
- Keep secrets in environment/configuration only.
- Add focused tests for new behavior.
- Run focused tests before the broader offline suite.
- Support retries and graceful external-service failure.
- Persist intermediate artifacts.
- Keep stages resumable and idempotent where practical.
- Log stage status and errors.
- Record cost and usage for expensive operations.
- Cache external research where appropriate.
- Preserve passing tests.
- Keep human approval gates explicit.
- Make thresholds and configuration values configurable.
- Avoid unrelated refactoring.

## Deferred Until Approved

- Full eight-minute image generation.
- 4K promotion.
- Camera motion or transitions.
- Multi-channel architecture.
- Automatic publishing before approval.
- Thumbnail automation before the pilot and packaging design are approved.
- Analytics-driven score changes before published inventory exists.

## Current Next Milestone

**M6 - YouTube Publishing and Scheduling**

M5 is complete for the current scope. M6 is implemented through the offline
provider contract and OAuth provider layer. The immediate next step is one
controlled live upload using configured Google OAuth credentials. M7 analytics
remains deferred until the YouTube video ID, URL, schedule, and publish status
are verified from that upload.

## Change Log

- 2026-09-24: Master milestone roadmap created from repository inspection and the supplied RITZZ eventual-goal specification.
- 2026-09-25: M1 implementation slice completed: persistent inventory, exact and near-duplicate checks, four-candidate discovery output, niche filtering, trend plus competitor evidence, duration/constraint capture, locked topic selections, and duplicate prevention. Focused M1 tests passed (46); full offline suite passed (301, one live test deselected). Live discovery returned four candidates with competitor evidence; all remained REVIEW pending human approval.
- 2026-09-25: M2 started: added deterministic research claim/source validation, conservative contradiction flags, persisted validation reports, FAIL-before-Outline behavior for unsupported important claims, REVIEW guidance for low-confidence claims, and focused tests (11 passed).
- 2026-09-25: M2 live validation completed against `cache/m2_live_validation/research.json`: 7 sources and 5 key facts were produced; validation correctly returned FAIL because a high-importance claim referenced an unlisted MythBusters URL. The report is preserved at `cache/m2_live_validation/research_validation.json`.
- 2026-09-25: M2 validation milestone completed for the current scope. Focused M2 tests passed (11); full offline suite passed (306, one live test deselected). M3 is now the active implementation milestone.
- 2026-09-25: M3 completed for the current scope: added `ProductionConfig` persistence and propagation through Research, Outline, Script, Voice, static Storyboard, and audio-timed Storyboard. Added end-to-end non-default duration coverage. Focused M3 tests passed (58); full offline suite passed (312, one live test deselected).
- 2026-09-25: M4 started: added persisted `pipeline_state.json`, resumable plan artifact reuse, pre-render image/audio validation, and focused pipeline coverage (7 passed). Full offline suite passed (313, one live test deselected).
- 2026-09-25: M4 QA slice completed: added stage-specific failure persistence, post-render technical QA status, and explicit pending human approval in `VideoProductionResult`. Full offline suite remains 313 passed, one live test deselected.
- 2026-09-25: M4 remaining work clarified: cost/usage logging, explicit retry-from-stage control, and broader failed-stage/QA integration coverage remain before M4 completion.
- 2026-09-25: M4 completed for the current scope: added `retry_from_stage`, downstream artifact invalidation, per-stage attempts, `pipeline_usage.json` timing/error records, and retry integration coverage. Focused pipeline tests passed (8); full offline suite passed (314, one live test deselected). M5 is now the next milestone.
- 2026-09-25: M5 completed for the current scope: added packaging artifacts for title options, selected title, thumbnail brief, description, tags, category, and workflow integration. Focused packaging and workflow tests passed.
- 2026-09-25: M6 offline/provider scope completed: added approval and schedule gates, project-level publish orchestration, persisted publish results, `FakeYouTubeProvider`, and opt-in OAuth `YouTubeProvider` support with scheduled `publishAt` mapping. Focused publishing tests passed (6); full offline suite passed (325, one live test deselected). Live OAuth upload verification remains pending before M7.
- 2026-09-26: M6 approval gate hardened: `publish_project` now requires an existing approved artifact and a matching approver identity instead of creating approval itself. Focused publishing/provider tests passed (9). Live upload remains pending because OAuth credentials are not configured.
