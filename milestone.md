# RITZZ Studio Milestones

Last verified: 2026-09-25

This file is the current status source for the project. The older roadmap in
`docs/Milestone.md` points here.

## Current milestone: YouTube Publishing and Scheduling

**Status: OFFLINE PROVIDER SCOPE COMPLETE; LIVE OAUTH UPLOAD VERIFICATION PENDING**

M1 through M5 are complete for the current scope. M6 now has explicit approval
and schedule artifacts, project-level publish orchestration, publish result
persistence, and an opt-in OAuth `YouTubeProvider` with scheduled `publishAt`
support. The offline suite passes 325 tests with one live web-search test
deselected. The project publish wrapper now requires a separately recorded
approved artifact and verifies that the caller's approver identity matches;
focused publishing/provider tests pass (9).

The next action is a controlled upload after configuring Google OAuth
credentials. No client-secret/token files or YouTube/Google OAuth environment
variables are currently configured, so no live upload was attempted.
M7 analytics work remains blocked until the YouTube video ID, URL, schedule, and
publish status are verified from a real upload.

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

- ElevenLabs defaults: stability `0.72`, similarity `0.75`, style `0`, speaker
  boost enabled, speed `0.95`.
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

