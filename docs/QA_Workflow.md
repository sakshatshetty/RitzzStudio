# RITZZ QA Workflow

Every project records stage QA history at `projects/<project>/qa/qa_report.json`. Each stage entry has `PASS`, `REVIEW`, or `FAIL`, checks, findings, recommendations, reviewer, and attempt number. Project status is aggregated from the latest attempt for each stage; a passing correction can clear an earlier failure while preserving its history.

## Always-on checks

- Research: source-reference coverage, claim confidence, and possible contradictions. `FAIL` blocks outlining; `REVIEW` is preserved for cautious wording and human judgment.
- Outline: section-duration sum and configured duration band.
- Script: structure, research/outline topic alignment, word count, duration, and the opening hook's match to the spoken first section and approximate 10-second length.
- Packaging: required title, description, and tags.
- Voice: measured minimum duration and character alignment when generated into a project audio directory. Too-short audio is rejected before scene timing; it is not stretched.
- Audio-timed storyboard: continuous timeline, prompts, static camera, hard cuts, and one-word uppercase editorial formatting.
- Render: image validity, scene order, gaps/overlaps, duration consistency, video/audio streams, and timeline coverage.

## Optional AI review

The content CLI asks whether to run additional AI review for research, outline, script, and packaging. AI `FAIL` on Research, Outline, or Script triggers at most one forced regeneration with findings/recommendations added as correction guidance; a second `FAIL` stops the workflow. `REVIEW` is recorded and does not silently change the artifact. Packaging is reviewed but not automatically rewritten.

The production-video CLI separately offers opt-in OpenAI vision review before rendering. It checks each generated image against its narration and visual description, and checks whether an embedded editorial word fits that scene. A clear mismatch triggers one targeted image regeneration for that scene; a `REVIEW` with a concrete correction prompt also triggers that bounded repair. An editorial word may move to an adjacent scene only when the 3–4-scene callout cadence remains valid. Original images are retained under `qa/image_repair/`, the initial findings and repair verification are both recorded in QA history, the updated storyboard and image manifest are saved, and each changed scene is reviewed again. A remaining `FAIL` stops rendering; ambiguous `REVIEW` findings without a concrete fix remain for human judgment rather than prompting speculative regeneration. This path incurs per-scene review cost and possible image-generation cost.

## Current limits

- AI reviews are advisory judgments, not proof that facts or images are correct. `REVIEW` requires human judgment.
- Voice QA is deterministic duration/alignment validation; it does not use an AI audio-quality reviewer.
- Deterministic render QA runs after video generation. It checks image readability, scene order, gaps/overlaps, timestamp coverage, scene-plan/audio duration, rendered audio/video streams, and rendered-video/audio duration (within 0.25 seconds). On a synchronization-related `FAIL` or timeline-drift `REVIEW`, the pipeline rebuilds the synchronized plan and rerenders once, then records the final result.
- The separate `run_pilot_audio_image_match.py` check compares each current audio-timed scene image with that scene's narration and timestamp range. It is an AI relevance check, not waveform alignment; the deterministic post-render QA is the audio/video synchronization check.
- Full image/narration AI review is opt-in and has not been recorded as complete for the current pilot. Preserve outputs and QA findings; do not treat an unrun reviewer as PASS.
- `enable_ai_qa` on `ContentWorkflow.run` and `enable_image_ai_qa` on the video pipeline request control whether these reviews run.

## Current pilot QA status

For `20260820_001_why_do_pirates_wear_eye_patches/pilot_3min/revision_v2`, deterministic technical QA is **PASS**: 54 scenes, audio 225.326440 seconds, video 225.333333 seconds (0.006893-second difference), no gaps or overlaps, and zero storyboard-to-render timeline drift. The saved semantic status remains **REVIEW**: local visual review covered 14 editorial frames, while full narration-to-image review is still pending.
