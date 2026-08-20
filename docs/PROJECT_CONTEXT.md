# Ritzz Studio - Project Context

> Portable context document for continuing the Ritzz Studio project in a new chat.
> Last updated: 20 August 2026

---

# 1. Project Overview

**Project:** Ritzz Studio

**Purpose:** Build an automated AI-powered YouTube video production system for the user's YouTube channel, Ritzz.

The target content is inspired by the visual/explainer style of the referenced MackExplains channel, but with a distinct Ritzz identity and different topics.

The system should eventually turn a topic into a finished YouTube video with minimal manual work.

Target pipeline:

Topic
↓
Research
↓
Outline
↓
Script
↓
Storyboard
↓
Image Generation
↓
Voice Generation
↓
Video Assembly / DaVinci Resolve
↓
Thumbnail
↓
Final Video
↓
Future: YouTube Upload

---

# 2. Channel Direction

**Channel name:** Ritzz

**Niche:** Mixed curiosity / educational explainers

**Audience:** General audience

**Tone:** Curious, educational, light humor

**Recurring narrator/mascot:** No

**Video length:** Approximately 8 minutes

**Upload schedule:** Tuesday and Saturday

**Production target:** 2 videos per week

**Target first video launch:** 7 September 2026

**Working schedule:** 3 hours per day, Monday through Saturday; Sunday is off.

---

# 3. Content Philosophy

Ritzz should focus on questions that naturally create curiosity.

Example topic style:

- Why do cats purr?
- Why are bananas curved?
- Why do pirates wear eye patches?
- Why do airplanes have oval windows?
- Why is the sky blue?

The goal is not to clone MackExplains. The goal is to create a recognizable Ritzz style inspired by the general animated-explainer format.

The videos should prioritize:

1. Strong hooks
2. Curiosity gaps
3. Clear explanations
4. Interesting/surprising facts
5. Good retention
6. Consistent visual identity
7. Accurate research

---

# 4. Visual Direction

The intended visual style is animated/cartoon/animatic rather than photorealistic.

The reference visual style discussed with the user has:

- Simple cartoon characters
- Bold/clean outlines
- Simple backgrounds
- Expressive faces
- Educational explainer feel
- 16:9 composition
- Images changing roughly every 3–5 seconds

Ritzz should eventually have its own Style Bible and Character/Visual Bible rather than copying another channel exactly.

---

# 5. Technical Architecture

The application is being built as a modular Python application.

Core principle:

**Each module should have one responsibility.**

Planned architecture:

Topic
↓
Project Manager
↓
Research Engine
↓
Outline Engine
↓
Script Engine
↓
Storyboard Engine
↓
Image Generator
↓
Voice Generator
↓
Video Builder
↓
Thumbnail / Publishing

Modules communicate primarily through structured JSON artifacts.

Example:

research.json
↓
outline.json
↓
script.json
↓
storyboard.json

Every major stage should be resumable and cached so failed jobs do not require regenerating everything.

---

# 6. Project-Based Architecture

Every video is an independent project.

Example:

projects/
└── 20260820_001_why_do_pirates_wear_eye_patches/
    ├── project.json
    ├── research/
    ├── outline/
    ├── script/
    ├── storyboard/
    ├── images/
    ├── audio/
    ├── video/
    ├── thumbnail/
    ├── exports/
    └── logs/

The Project Manager creates and tracks these project directories.

The `projects/` directory is intentionally ignored by Git because it contains generated video/project content.

---

# 7. Development Environment

**OS:** Windows

**Project root:**

D:\AIStudio\RitzzStudio

**Python:** Python 3.14.6 currently in the virtual environment.

Note: Python 3.12 was originally planned, but Python 3.14.6 is currently working successfully. Do not downgrade unless a real dependency compatibility problem appears.

**Virtual environment:**

D:\AIStudio\RitzzStudio\.venv

The virtual environment is active and working.

---

# 8. Workspace Structure

Current main structure:

D:\AIStudio\
├── RitzzStudio\
├── Assets\
├── Videos\
├── Exports\
├── Archive\
└── Tools\
    ├── ffmpeg\
    ├── models\
    └── whisper

RitzzStudio contains:

├── docs\
├── modules\
├── prompts\
├── schemas\
├── tests\
├── resources\
├── assets\
├── cache\
├── logs\
├── output\
├── projects\
├── templates\
├── scripts\
├── examples\
├── storage\
├── .vscode\
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── .env
└── .env.example

---

# 9. Installed / Planned Technology

Current / planned stack:

- Python
- OpenAI API
- ElevenLabs API
- FFmpeg
- DaVinci Resolve
- Whisper (future subtitle/timestamp processing)
- Pydantic
- pytest
- Rich
- requests
- python-dotenv
- Git / GitHub
- VS Code

Image generation will initially be implemented through an appropriate API and can later be changed without redesigning the rest of the pipeline.

---

# 10. OpenAI Setup

OpenAI API account is configured.

API key is stored in `.env`.

Never commit `.env`.

OpenAI health check has successfully passed.

The health check is located at:

modules/common/health_check.py

The exact model/API call strategy should be finalized when building the Research Engine rather than assuming an old model name.

---

# 11. Project Manager - Completed

The Project Manager is the first production module and is working.

Files:

modules/project/__init__.py
modules/project/manager.py
modules/project/models.py

Responsibilities:

- Create project
- Generate project ID
- Generate slug
- Create project directory structure
- Save project.json
- Load project
- Update status
- Mark pipeline steps complete

Project IDs use the format:

YYYYMMDD_NNN

Example:

20260820_001

The project model tracks:

- project_id
- title
- slug
- status
- created_at
- pipeline steps

Current tracked steps:

- research
- outline
- script
- storyboard
- images
- voice
- video
- thumbnail

---

# 12. Project Manager Tests

Automated tests exist at:

tests/test_project_manager.py

Current tests:

- Create project
- Load project
- Update status
- Complete step
- Invalid step handling

Current result:

**5 tests passed**

pytest is working successfully.

---

# 13. app.py

The root application entry point is:

D:\AIStudio\RitzzStudio\app.py

It currently:

1. Displays Ritzz Studio
2. Asks for a video topic
3. Creates a project using ProjectManager
4. Displays project ID/location

Example:

python app.py

Input:

Why Do Pirates Wear Eye Patches?

Creates:

projects/20260820_001_why_do_pirates_wear_eye_patches/

The project creation flow has been tested successfully.

---

# 14. Git Status / Milestone

Git repository is already initialized.

Current branch:

Branch1

The Project Manager work was committed.

Commit:

0559a38

Commit message:

feat : add project manager

Tag:

v0.1-foundation

The foundation has been pushed/merged to the remote repository.

The `.gitignore` protects:

- .env
- .venv/
- projects/
- cache/
- output/
- logs/
- Python cache files
- VS Code runtime files
- pytest cache

---

# 15. Completed Milestones

## Foundation

Status: COMPLETE

Completed:

- Workspace
- Python environment
- Virtual environment
- OpenAI API
- Health check
- Git
- Project model
- Project Manager
- Automated tests
- app.py integration
- v0.1-foundation Git tag

---

# 16. Current Milestone

## Research Engine

Status: NEXT

The next task is to design the Research Engine contract before writing implementation code.

The desired pipeline:

Topic
↓
Web/source research
↓
Source collection
↓
AI research organization
↓
Fact verification / confidence
↓
research.json

The Research Engine should NOT write the final YouTube narration.

It should produce structured factual research that the Outline Engine can use.

---

# 17. Research JSON - Planned Direction

A planned research artifact may contain:

- topic
- category
- core_question
- short_answer
- key_facts
- historical/scientific context
- common myths
- surprising facts
- possible story angles
- sources
- confidence / verification information

The exact schema has NOT been finalized yet.

Do not assume the above is final. Design the contract first.

---

# 18. Planned Milestones

## Phase 1 - Content Brain

Research Engine
↓
Outline Engine
↓
Script Engine

Target: first week

---

## Phase 2 - Visual Planning

Storyboard Engine
↓
Style Bible
↓
Character/visual consistency
↓
Image prompts

---

## Phase 3 - Production

Image generation
↓
ElevenLabs voice
↓
Whisper timestamps/subtitles
↓
DaVinci Resolve automation
↓
Thumbnail

---

## Phase 4 - Publishing

Title
Description
Thumbnail
Upload

Automatic YouTube upload is a future feature and is NOT required for the first video.

---

# 19. MVP Scope for 7 September

Must-have:

- Research
- Outline
- Script
- Storyboard
- Image generation
- Voice generation
- DaVinci/video assembly
- Thumbnail
- Final rendered video

Not required for first video:

- GUI
- SQLite
- Multi-channel support
- Docker
- Queue management
- Automatic YouTube upload
- Shorts generation
- Advanced animation

The priority is getting one high-quality Ritzz video published by 7 September 2026.

---

# 20. Development Rules

1. One module = one responsibility.
2. Prefer structured JSON between pipeline stages.
3. Save AI outputs so work can be resumed.
4. Cache expensive API operations.
5. Do not regenerate successful stages unnecessarily.
6. Every feature should have tests where practical.
7. No hardcoded API keys.
8. Use environment variables for secrets.
9. Use logging instead of scattered print statements in production modules.
10. Use pathlib for filesystem operations.
11. Use type hints.
12. Use Pydantic for external/AI-generated data validation where appropriate.
13. Do not add large features until the current milestone is stable.
14. Keep the MVP focused so the 7 September target remains realistic.

---

# 21. Important Design Principle

Ritzz Studio is being built as a real reusable software system, not as a collection of one-off scripts.

The final architecture should allow:

Topic
↓
Project Manager
↓
Research
↓
Outline
↓
Script
↓
Storyboard
↓
Images
↓
Voice
↓
Video

with each stage independently replaceable or rerunnable.

For example, changing the image provider should not require rewriting the Research or Script engines.

---

# 22. Current Immediate Next Step

The next coding session should start with:

**Design the Research Engine contract and research.json schema.**

Do NOT immediately write research.py.

First determine:

- What the Research Engine receives
- What it returns
- How sources are represented
- How facts are represented
- How confidence/verification is represented
- What the Outline Engine needs from research
- How web research will be performed
- How research results will be cached

Then implement and test Research Engine v1.

---

# 23. Target Timeline

Current date in project context:

20 August 2026

First video target:

7 September 2026

Available working schedule:

Monday-Saturday
3 hours/day

Sunday:

OFF

The schedule is approximately 18 focused hours/week.

The priority is a working MVP rather than building every planned feature.

---

# 24. How to Continue in a New Chat

If this project is continued in a new ChatGPT conversation, provide or reference this file and say:

"Continue Ritzz Studio using PROJECT_CONTEXT.md. We are currently at the Research Engine milestone."

The next task is to design the Research Engine contract/schema before coding.
