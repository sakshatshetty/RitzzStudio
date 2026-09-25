# RITZZ Studio — Codex Project Instructions

Project root: `D:\AIStudio\RitzzStudio`

## Production decisions

- One YouTube channel only.
- Mixed Curiosity niche.
- Target video length: 8 minutes.
- Publishing target: Tuesday and Saturday.
- Simple 2D stickman/cartoon visual style.
- Static images only.
- Hard cuts only.
- NO pan, zoom, camera motion, or transitions.
- Visual pacing: aim for about 3 seconds per image. Keep an image while narration stays on the same idea; cut when the narrative changes. Merge short phrase fragments from the same idea instead of creating 1-second images.
- Editorial callouts every 3–4 scenes.
- Production editorial callouts: exactly ONE WORD, uppercase.
- Editorial text is embedded in images, not subtitles.
- Actual narration timestamps are the source of truth for final synchronization.
- Use the existing RITZZ ElevenLabs professional voice.
- Use OpenAI image generation.
- Use FFmpeg for rendering.

## Current pilot

Topic: `Why Do Pirates Wear Eye Patches?`

Project ID: `20260820_001_why_do_pirates_wear_eye_patches`

Legacy phrase-split pilot storyboard (do not use for new image generation):
`projects\20260820_001_why_do_pirates_wear_eye_patches\pilot_3min\storyboard_dynamic.json`

Audio-timed pilot storyboard:
`projects\20260820_001_why_do_pirates_wear_eye_patches\pilot_3min\storyboard_audio_timed.json`

- 37 narrative scenes derived from actual ElevenLabs character timestamps
- 146.564 seconds, matching dedicated pilot narration
- scene holds: 3.031–5.677 seconds; median 3.982 seconds
- phrase fragments from the same visual narrative are merged
- static camera and hard cuts
- current narration is shorter than the 180-second target; revise story length before generating replacement audio if an exact 3-minute runtime is required

Legacy pilot images (preserve, but do not use for the audio-timed pilot):
`projects\20260820_001_why_do_pirates_wear_eye_patches\pilot_3min\images`

- 83/83 completed
- 0 failed
- manifest exists

Current focused dynamic storyboard tests:
`15 passed`

Existing 7:42 narration belongs to the longer production and must not be used for the pilot. Dedicated pilot narration currently exists at 146.564 seconds. If the pilot needs to reach 180 seconds, revise the story before generating replacement narration; do not stretch audio.

## Current pipeline order

1. Create the pilot story and scene descriptions.
2. Generate dedicated narration from the story.
3. Use actual narration alignment to group same-idea phrase fragments and set scene timestamps.
4. Generate images from the audio-timed storyboard.
5. Render the audio and timed images with static camera and hard cuts.

Do not generate another image set until the audio-timed storyboard has been reviewed. New audio-timed images belong in `pilot_3min\images_audio_timed`; do not overwrite the legacy 83 images.

## Next milestone

Complete the revised pilot:

1. Review the audio-timed storyboard and narration pacing.
2. Generate images from that storyboard.
3. Render the revised pilot.
4. Review image/narration matches and watch the video.

## QA requirements

Technical:
- all images exist/readable
- audio exists
- no gaps
- no overlaps
- correct scene order
- duration consistency
- timestamp coverage
- actual audio/video duration consistency

Semantic:
- narration ↔ actual image relevance
- narration ↔ visual description relevance
- editorial word ↔ image/context relevance

Classify as PASS / REVIEW / FAIL. Do not automatically delete/regenerate solely from model confidence.

## Coding workflow

The user prefers complete file replacements rather than patch snippets.

Before changing code:
- inspect actual files
- inspect tests
- inspect callers/usages
- preserve existing working APIs

After changes:
- run focused tests
- then broader tests
- do not weaken/delete tests to make code pass

Do not guess API signatures if the repository can be inspected.

Keep legacy dynamic engine helpers if tests depend on them, including:
- `_normalize_text`
- `_word_count`
- `_editorial_score`
- `_build_editorial_text`

## Cost discipline

Image generation is expensive. Do not start full 8-minute image generation until the 3-minute pilot has passed technical QA, semantic QA, and human review.

## Do not work on yet

- full 8-minute dynamic image generation
- 4K promotion
- camera motion
- transitions
- thumbnails
- upload automation
- analytics loop
- multi-channel support
