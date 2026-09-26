# Changelog

## 2026-09-26

- Added a project QA ledger at `qa/qa_report.json` with per-stage status,
  findings, recommendations, reviewer, and attempt history.
- Added deterministic QA records for research, outline, script, packaging,
  voice, audio-timed storyboard, and rendered-video technical validation.
- Added opt-in structured AI review for research, outline, script, and
  packaging. Research, outline, and script receive at most one feedback-guided
  regeneration; unresolved failures stop the content workflow.
- Added opt-in per-scene AI image/narration/editorial review to the video
  pipeline. This adds one vision review per scene and reports failures without
  automatically replacing generated images.
- Added CLI choices for the extra AI QA calls and documented gates and limits
  in [docs/QA_Workflow.md](docs/QA_Workflow.md).

## 2026-09-25

- Completed M5 packaging integration for titles, thumbnail briefs, and metadata.
- Completed the M6 offline publishing contract with approval and schedule gates.
- Added project-level publish orchestration and persisted publish results.
- Added the opt-in OAuth `YouTubeProvider` with title, description, tags,
  category, notification, privacy, and scheduled `publishAt` mapping.
- Added YouTube setup documentation in
  [docs/YouTube_Publishing_Setup.md](docs/YouTube_Publishing_Setup.md).
- Verified the focused publishing tests: 6 passed.
- Verified the full offline suite: 325 passed, 1 deselected.
- Remaining M6 gate: perform one controlled live upload with Google OAuth
  credentials. M7 analytics remains planned until that verification passes.

## 2026-09-24

- Completed M4 resumable production orchestration for the current scope,
  including stage state, retry control, asset validation, usage records, and
  technical QA boundaries.