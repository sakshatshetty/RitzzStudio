# RITZZ Studio Milestones

Last verified: 2026-09-25
Last verified: 2026-09-28

This file is the current status source for the project. The older roadmap in
`docs/Milestone.md` points here.

## Current milestone: Approval-Aware Pipeline Orchestration and Retryability

**Status: M8 ACTIVE — HUMAN-APPROVAL-AWARE AUTOMATION LAYER**

**Next validation milestone: M9 — FIRST REPEATABLE PRODUCTION / VIDEO #2 READINESS**

All videos generated during M8 implementation and M9 validation are test videos.
They must remain private or unlisted unless separately approved for testing. V1
is the first actual public video and will be created only after the pipeline,
approval flow, rendering, upload, and end-to-end tests are complete.

M9 does not introduce a new architecture. It is the first real validation of the
existing M0–M6 production flow with a genuinely new second video, using the
current approved pipeline and the same human review gates. The goal is to prove
the workflow is repeatable in real production: a new project, preserved quality
checks, publish approval, and the first post-publish learning signal for M7.

M6 is complete for the current scope. The live OAuth upload was verified with a
real YouTube upload that returned a valid video ID and URL, and the project
publishing flow has been validated end-to-end with explicit approval plus
schedule handling.

M7 is implemented for the repository scope: published projects can be recorded
in an inventory, analytics snapshots are persisted with raw/normalized/derived
layers, learning aggregates are computed, and a CLI exists to collect analytics
for a published project. The project-level contract is validated by focused
tests and does not claim a live YouTube Analytics API fetch unless the
configured OAuth credentials are available and the user chooses to run the live
collector against a published video.

The next milestone is M8: approval-aware pipeline orchestration and retryability.
This milestone focuses on the missing parts required for a production-ready
human-controlled pipeline rather than a fully autonomous system:

- full orchestration across all stage transitions
- stronger end-to-end resume/retry coverage
- final approval automation around packaging and publish readiness
- better operational monitoring and stage status reporting
- integration of M7 learning feeds when they exist

The architecture remains explicit about human approval gates. Automation should
The architecture remains explicit about human approval gates. Automation should
cover stage execution, state persistence, and recovery, while approval,
scheduling, and final publish remain explicit and reviewable.

The selected CI/CD control plane is GitHub Actions. Normal video production is
browser-driven from the GitHub Actions workflow UI; the user does not need to
run a command-line script for each video. The workflow discovers four trending
topic candidates, presents them as numbered choices 1 through 4, and pauses for
human selection and approval before continuing.

The same workflow pauses for human approval after video generation and QA,
before upload, and before public publication. GitHub Actions manages stages,
artifacts, logs, retries, and approvals while the existing RITZZ Python modules
remain the production workers. Dynamic topic selection is currently handled by
a GitHub issue created for the run: a trusted collaborator replies with 1, 2, 3,
or 4, and the workflow resumes into the protected approval environment.
- GitHub Actions workflow control with browser-only execution
- numbered trending-topic selection: 1, 2, 3, or 4
- approval pauses for topic choice, generated video, upload, and publication

M8 is focused on reliability and observability. Once the reliability layer is
in place, M9 becomes the first repeatable production test: create a new video #2,
run the approved M0–M6 flow, publish it, and let M7 begin collecting analytics
from that real second video. M10 is the future learning-feedback milestone that
connects M7 insights back into the M0 topic-selection and production decision
process.

See [CHANGELOG.md](CHANGELOG.md) for the milestone history and
[RITZZ Master Milestones](docs/RITZZ_Master_Milestones.md) for the long-term
roadmap.

The interactive app now offers vidIQ topic discovery or manual topic entry.
Discovery supports TRENDING and EVERGREEN modes, uses the official vidIQ MCP
endpoint, records available evidence, scores supported signals, and caches
reports. The user chooses a candidate before content preparation begins.

The app also offers competitor research: it queries vidIQ outlier videos for a
RITZZ topic family, presents the top three success examples, and lets the user
send one selected idea into Research -> Outline -> Script.

The selected or manual topic runs through the existing Research -> Outline ->
Script engines. Successful stages update project metadata; selection
provenance is saved to `topic_selection.json`. Existing 8-minute defaults
remain unchanged.

The recommendation gate preserves all provider candidates for auditability,
deduplicates close topics, and marks candidates as `RECOMMENDED`, `REVIEW`, or
`REJECTED` before human selection.

M2 is complete for the current scope. Research validation checks claim source
coverage and confidence before Outline. Unsupported important claims fail the
workflow; low-confidence claims remain REVIEW with cautious-wording guidance.

M3 is complete for the current scope. `ProductionConfig` now reaches Research,
Outline, Script, Voice, static Storyboard, and audio-timed storyboard APIs while
preserving the current eight-minute default. The full offline suite passes 312
tests.

M4 is now active: unify production stages with resumable state, asset
validation, cost logging, and explicit QA/approval boundaries.

M4 is complete for the current scope. The video production pipeline now
persists stage state, reuses existing plan artifacts, supports explicit
retry-from-stage control, records per-stage attempts and elapsed time in
`pipeline_usage.json`, rejects invalid assets before rendering, runs technical
QA, and leaves human approval explicitly pending. Full offline suite: 314
passed, one live test excluded.

M5 is now active: packaging research, title options, thumbnail generation, and
metadata generation remain to be implemented. Publishing and analytics remain
deferred.

Live M2 validation was exercised against a real pirate-eyepatch research
artifact. It correctly returned FAIL for an important claim citing an unlisted
MythBusters URL; the report remains in `cache/m2_live_validation` for review.

The first market-intelligence layer is also implemented: vidIQ outlier research
can inspect successful long-form videos separately from keyword scoring. Repeated
outlier patterns should be collected before they influence the recommendation
score.

The competitor workflow saves its normalized report to
`cache/topic_intelligence/market_intelligence.json`.

| Stage | Status | Evidence |
| --- | --- | --- |
| Topic discovery | Implemented; live-validated for rising `history` category | `modules/topic_intelligence` discovers MCP tools and schemas, parses structured candidate data, and caches reports. One live query returned four candidates. |
| Opportunity scoring | Implemented; live editorial scoring validated | Scores relative demand, momentum, competition categories, and structured OpenAI editorial assessments. The live report scored four candidates with 75% evidence completeness because momentum and competition were unavailable; missing signals remain visible and model/prompt versions are saved. |
| Human selection | Implemented | `app.py` displays candidates and allows selection or manual topic entry. |
| Manual topic path | Implemented | Manual entry bypasses discovery and uses the same content workflow. |
| Research -> Outline -> Script | Implemented | `modules/content_workflow/engine.py` runs existing engines in order and updates project steps after successful outputs. |
| Live vidIQ connection | Working for rising categories | Live validation found and fixed three issues: loose substring argument mapping, language code normalization, and the fact that rising queries require a vidIQ category rather than the free-form channel niche. A forced-refresh `history` query returned four candidates and the full coordinator completed editorial scoring. |

See [Topic Intelligence Design](docs/Topic_Intelligence_Design.md) for
architecture, setup, and current limitations. Do not share the API key in chat
or commit `.env`.

### Run the workflow

Run `python app.py`, then choose vidIQ discovery or manual entry. TRENDING mode
asks for a vidIQ rising category (defaults to `history`; `ALL` leaves results
unscoped) and timeframe. Then choose a candidate, confirm or edit its topic,
and the app creates a project and runs Research -> Outline -> Script.

### Current implementation limits

- The `history` rising category is live-validated and returned four records.
  The `ALL` mode can return trends outside Mixed Curiosity; selecting a
  supported category gives vidIQ's relevant rising-keyword set.
- Response parsing tests also cover nested payloads, arrays, embedded JSON,
  labeled rows, and Markdown tables.
- The adapter only maps explicit topics and metrics; it does not invent either.
- Editorial dimensions such as audience fit, curiosity, visual storytelling,
  researchability, differentiation, and saturation are preliminary OpenAI
  judgments, not factual research or verified saturation measurements. If the
  assessment fails, its missing values lower score completeness.
- The OpenAI editorial assessment is live-validated. The `EVERGREEN` provider call authenticates but currently returns only a generic query-derived row, so its argument mapping and usefulness still need validation before treating evergreen discovery as operational.

### Verification

- Topic intelligence tests: **30 passed**.
- Live discovery report: `cache/topic_intelligence/b9f6e588f5bf0ff48ccd0bdb66a9edb87ab35b9b9b18fd70c4a90e575a57b02b.json` (four `history` candidates; editorial scoring completed; 85% evidence completeness; one recommendation passed the validation gate).
- Latest live M1 validation: report `cache/topic_intelligence/068abdebe11a9ba040d7e92faaedc8af8476ff85cd7d8f86870bf124d2a3b89d.json` returned four candidates with competitor evidence attached. All four were marked `REVIEW`, preserving the human approval gate.
- Broad offline suite excluding the live OpenAI web-search test: **289 passed**.
- No image generation or full 8-minute production was run.

## Current production architecture

The intended production flow after content preparation remains:

```text
Selected or manual topic
  → Research
  → Outline
  → Script
  → Narration audio and character alignment
  → Group narration into audio-timed scenes
  → Generate images
  → Synchronize and render with FFmpeg
  → Review the rendered video
```

Production constraints remain: static images, about three seconds per scene when
the narrative supports it, hard cuts, and actual narration alignment as the
timing source. Do not start full 8-minute image generation until the revised
pilot passes its QA and human review requirements.
## Recent voice-pipeline change

Implemented for future narration requests:

- ElevenLabs defaults: speed `1.0`, stability `0.90`, similarity `0.75`,
  style exaggeration `0`, speaker boost enabled.
- Script generation prompts request natural spoken punctuation. Script section
  endings are normalized before synthesis, and requests receive a final-stop
  safeguard.
- Standard script narration carries `Script.target_duration_seconds` as its
  minimum. FFprobe measures the generated audio; short audio is marked failed
  and cannot proceed to scene timing. The error recommends an approximate
  script expansion; it does not rewrite or regenerate the script automatically.
- The synchronizer also rejects narration metadata whose measured duration is
  below its recorded minimum.

## Current pilot status

Topic: **Why Do Pirates Wear Eye Patches?**

Project ID: `20260820_001_why_do_pirates_wear_eye_patches`

Latest revised pilot artifacts are in
`projects/20260820_001_why_do_pirates_wear_eye_patches/pilot_3min/revision_v2`.

| Checkpoint | Status |
| --- | --- |
| Revised audio-timed storyboard | 54 scenes |
| Dedicated audio | 225.326 seconds (3:45) |
| Audio-timed images | 54 generated |
| MP4 render | Present; 225.333 seconds |
| Technical QA | PASS; no reported issues, maximum timeline drift 0 seconds |
| Semantic narration/image QA | REVIEW; full automated review was blocked, and full scene-by-scene review remains incomplete |
| Full 8-minute production | Not started |

The user has said the revised video is much better. The earlier 83-image
phrase-split set is legacy; do not use it for new generation. The separate
legacy 96-image production set is not evidence that the revised 8-minute flow
has been completed.

## Test status

Last broad offline test run: **255 passed**. The live OpenAI web-search test
was excluded because it requires network access. Focused voice and duration
gate tests passed before that run.

## Production decisions

- One YouTube channel; Mixed Curiosity niche; target length 8 minutes.
- Existing RITZZ ElevenLabs voice and OpenAI image generation.
- Static images and hard cuts only. No pan, zoom, camera motion, or transitions.
- Editorial callouts are embedded in images, one uppercase word, about every
  3â€“4 scenes.
- Do not start full 8-minute image generation until the revised pilot's QA and
  review requirements are complete.
- Do not promote to 4K or add upload automation, thumbnails, analytics, or
  multi-channel support yet.
