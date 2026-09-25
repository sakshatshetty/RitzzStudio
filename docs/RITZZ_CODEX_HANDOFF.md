# RITZZ Studio — Codex Handoff

## Purpose

This is the current handoff for the RITZZ Studio YouTube automation project. Use the actual repository files as the source of truth for code and tests.

Project root:
`D:\AIStudio\RitzzStudio`

## 1. RITZZ Goal

Build one automated faceless YouTube channel called **RITZZ**.

- Niche: Mixed Curiosity
- General audience
- Curious / explainer tone
- No recurring narrator character
- Target video length: 8 minutes
- Publishing target: Tuesday and Saturday
- Visual style: simple 2D stickman/cartoon illustrations
- Flat colors, thick black outlines, minimal shading
- Static images only
- Hard cuts only
- NO pan, zoom, camera motion, or transitions
- Visual pacing: aim for about 3 seconds per image. Keep it while narration stays on the same idea; cut when the narrative changes. Merge short phrase fragments instead of creating 1-second images.
- Editorial callouts embedded inside selected images
- Editorial callouts every 3–4 scenes
- Production editorial callouts: exactly ONE WORD, uppercase, contextual and memorable
- Actual narration timestamps are the source of truth for final synchronization
- Keep the architecture single-channel only

## 2. Target Architecture

```text
Topic
  ↓
Research
  ↓
Outline
  ↓
Script and narrative storyboard
  ↓
ElevenLabs Narration
  ↓
Character Timestamps
  ↓
Audio-Timed Scene Grouping
  ↓
Image Generation from Timed Scenes
  ↓
Actual Timeline Synchronization
  ↓
FFmpeg Render
  ↓
Automated Video QA
  ↓
Final Video
```

Later, after the pilot is approved: thumbnail, metadata, upload, topic intelligence, analytics/learning loop.

## 3. Current Environment

- Windows / PowerShell
- Project: `D:\AIStudio\RitzzStudio`
- Python 3.14.6
- `.venv`
- pytest 9.1.1
- openai 3.1.0
- FFmpeg 9.0.1

Root `.env` contains configuration such as:

```env
OPENAI_API_KEY=...
RITZZ_VOICE_ID=...
RITZZ_VOICE_MODEL=eleven_multilingual_v2
RITZZ_EDITORIAL_MODEL=gpt-5.4-mini
```

Never print API keys.

## 4. Completed Milestones

Completed and working:

- Foundation / project manager
- Research engine
- Outline engine
- Script engine
- Conventional storyboard engine
- Image models
- Image engine
- Batch image engine
- RITZZ image prompt builder
- OpenAI image provider
- ElevenLabs voice models/engine/provider
- Actual voice generation and timestamp/alignment validation
- Video assembly
- Audio/storyboard synchronization foundation
- FFmpeg rendering
- End-to-end 3-scene pipeline

Historical overall test milestones reached:

- 162 passed after video assembly
- 176 passed after synchronization
- 190 passed after motion implementation
- 196 passed after FFmpeg rendering
- 202 passed after end-to-end integration

Motion planning existed historically, but production decision is now **NO MOTION**.

## 5. Current Test Topic

Topic:
**Why Do Pirates Wear Eye Patches?**

Project ID:
`20260820_001_why_do_pirates_wear_eye_patches`

Project directory:
`D:\AIStudio\RitzzStudio\projects\20260820_001_why_do_pirates_wear_eye_patches`

Original conventional storyboard:
`storyboard\storyboard.json`

Original production storyboard:
- 96 scenes
- 480-second target
- roughly 5-second scenes

## 6. Visual Scene Pacing

The first full render used fixed 5-second scenes. The later phrase-split pilot went too far in the other direction: 1-second images are too brief to follow.

Current desired production behavior:
- Aim for roughly 3 seconds per image.
- Keep the same image while narration stays on the same idea.
- Cut when the narrative changes.
- Merge short phrase fragments that share one visual narrative.
- Set scene timestamps from actual narration alignment after audio generation.
- Static images
- Hard cuts only
- Editorial text every 3–4 scenes

## 7. Legacy Phrase-Split Storyboard

File:
`pilot_3min\storyboard_dynamic.json`

Legacy result (reference only; its 83 images are not for the revised pipeline):

```text
Scenes: 83
Duration: 180.000 seconds exactly
Minimum scene: 1.000 seconds
Maximum scene: 2.961 seconds
Editorial scenes: 23
Camera: STATIC
Transitions: HARD CUT
Editorial: ONE WORD
```

Focused dynamic storyboard tests:

```text
15 passed
```

The dynamic engine currently keeps legacy compatibility methods because existing tests depend on them:

- `_normalize_text`
- `_word_count`
- `_editorial_score`
- `_build_editorial_text`

Do not remove them without checking tests.

The revised audio-timed storyboard is `pilot_3min\storyboard_audio_timed.json`. It groups the 83 short beats into 37 audio-aligned image scenes. Current holds are 3.031–5.677 seconds (3.982-second median); this storyboard is the source for the next image generation.

## 8. Editorial System — CURRENT

Production editorial rule:

```text
Exactly ONE WORD
UPPERCASE
Maximum 20 characters
Contextual
Memorable
Not a subtitle
Not narration transcription
```

The LLM receives previous/current/next narration beats and chooses one memorable concept.

Recent valid examples:

```text
ICONIC
SYMBOL
ACCURACY
COSTUME
QUESTION
ORIGIN
INJURY
LOGICAL
MYTH
NIGHTVISION
PRACTICAL
EVIDENCE
MISLEADING
SOURCES
STEREOTYPE
STANDARD
DIFFERENCE
LEGEND
TRADITION
DANGER
SURVIVAL
```

## 9. Legacy Pilot Images

Directory:
`pilot_3min\images`

Result:

```text
Expected: 83
Completed: 83
Failed: 0
Pending: 0
```

Manifest:
`pilot_3min\images\image_manifest.json`

Preserve the existing 83 pilot images. Generate revised images in `pilot_3min\images_audio_timed` from the audio-timed storyboard; do not overwrite the legacy image directory.

The original 96-image production set is separate in:
`projects\20260820_001_why_do_pirates_wear_eye_patches\images`

## 10. Current Audio State

There is an original narration of approximately **7 minutes 42.6 seconds** and a dedicated pilot narration of **146.564 seconds**.

The 7:42 narration belongs to the original longer production. The dedicated pilot audio is 146.564 seconds, so it is shorter than the 3-minute target. The current audio-timed storyboard reflects that actual duration. If an exact 3-minute runtime is required, extend/revise the pilot story before generating another narration; do not stretch the audio.

The immediate next step is to review the audio-timed storyboard and then generate images for its scenes.

Use:
- existing RITZZ professional ElevenLabs voice
- `RITZZ_VOICE_ID`
- `RITZZ_VOICE_MODEL=eleven_multilingual_v2`

Dedicated pilot audio and character timestamps/alignment already exist in `pilot_3min`.

Suggested pilot outputs:

```text
pilot_3min\narration_3min.mp3
pilot_3min\narration_3min_timestamps.json
```

Follow the repository's existing voice implementation and naming conventions if they differ.

## 11. NEW REQUIRED MILESTONE — AUDIO/VIDEO QA

Before moving to full 8-minute production, the 3-minute pilot must include automated QA.

### A. Technical timing QA

For every scene validate:

- audio coverage
- image start/end
- actual narration start/end
- scene ordering
- no gaps
- no overlaps
- no missing timestamps
- no missing/corrupt images
- total duration consistency
- timeline drift

Example report:

```text
Scene 024
Expected start: 52.381s
Actual start:   52.741s
Drift:           0.360s
Status: REVIEW
```

### B. Semantic narration/image QA

Timing alone is insufficient. Validate actual generated images against:

- narration
- visual description
- image prompt
- editorial word when present

The semantic check should flag obvious mismatches such as narration about an eye patch while the actual image shows unrelated content.

Classification:

```text
PASS
REVIEW
FAIL
```

Do not automatically delete/regenerate images only from model confidence. Human review must remain possible.

## 12. Revised Pilot Flow

```text
Pilot story and narrative storyboard
        ↓
Generate dedicated ElevenLabs narration
        ↓
Generate character timestamps
        ↓
Group same-idea phrase fragments and set scene boundaries from audio alignment
        ↓
Generate images from the audio-timed storyboard
        ↓
Render with static hard cuts
        ↓
Review image/narration matches and watch the video
```

Important: after voice generation, actual timestamps become the source of truth for the final scene timeline.

## 13. Next Coding Steps

1. Review `storyboard_audio_timed.json` and its scene holds.
2. Generate the revised image set in `images_audio_timed`.
3. Render the audio-timed storyboard with static images and hard cuts.
4. Review image/narration matches and watch the revised pilot.
5. Do not promote to full 8-minute image generation until the pilot is approved.

## 14. Do NOT Do Yet

Do not:

- generate the full 8-minute dynamic image set
- promote to 4K yet
- add camera motion
- add transitions
- add multi-channel architecture
- build thumbnail automation
- build upload automation
- build topic intelligence
- build analytics learning loop
- replace working image/voice providers unnecessarily

## 15. Coding Preferences

User strongly prefers:

- full file replacements instead of small patches
- inspect the actual repository file/test before changing it
- preserve working modules and APIs
- focused tests before broad tests
- no guessed API signatures when the repository can be inspected
- do not regenerate expensive assets unnecessarily
- give one clear next command at a time when practical

## 16. Definition of Done — 3-Minute Pilot

```text
83 storyboard scenes                 PASS
180s storyboard target               PASS
1–3s scene limits                    PASS
23 one-word editorial callouts       PASS
83 images                            PASS
Dedicated ~3-minute narration        PENDING
ElevenLabs timestamps                PENDING
Audio/image synchronization          PENDING
No scene gaps/overlaps               PENDING
Semantic image/narration QA          PENDING
3-minute MP4                         PENDING
Human watch/review                   PENDING
```

## 17. Immediate Codex Instruction

Start from the actual repository state.

```text
Inspect the current voice provider/engine, synchronization engine,
render engine, existing production narration script, and tests.
Then build the dedicated 3-minute pilot narration using the existing
RITZZ ElevenLabs voice. Do not modify or replace working production
assets. Add tests, run focused tests, then proceed to synchronization
and automated technical/semantic QA for the 3-minute pilot.
```

Do not jump directly to full 8-minute production.
