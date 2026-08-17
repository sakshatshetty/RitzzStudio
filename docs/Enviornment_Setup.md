# Ritzz Studio - Environment Setup

This document describes everything required before development begins.

---

# Operating System

- Windows 11

---

# Development Tools

## Visual Studio Code

Extensions

- Python
- Pylance
- GitLens
- Black Formatter
- Ruff
- Error Lens

---

## Python

Recommended Version

Python 3.12.x

Verify

python --version

---

## Git

Verify

git --version

---

## FFmpeg

Install

Add FFmpeg to PATH

Verify

ffmpeg -version

---

## DaVinci Resolve

Install

DaVinci Resolve (Free)

No scripting configuration required yet.

---

## Visual Studio Build Tools

Install

Desktop Development with C++

---

# Project Folder

Recommended Structure

D:\AIStudio\

```
AIStudio/
│
├── RitzzStudio/
├── Assets/
├── Videos/
├── Exports/
├── Archive/
└── Models/
```

---

# Repository Structure

```
RitzzStudio/
│
├── docs/
├── modules/
├── prompts/
├── schemas/
├── assets/
├── cache/
├── output/
├── logs/
├── tests/
│
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── .env
└── .gitignore
```

---

# Python Virtual Environment

Create

python -m venv .venv

Activate (PowerShell)

.venv\Scripts\Activate.ps1

---

# Required Python Packages

Initial Packages

- openai
- python-dotenv
- pydantic
- requests
- rich

Install

pip install openai python-dotenv pydantic requests rich

Freeze

pip freeze > requirements.txt

---

# Accounts Required

## OpenAI

Purpose

- Research
- Outline
- Script
- Image Generation

API Key

Stored inside

.env

---

## ElevenLabs

Purpose

Voice generation

---

## GitHub

Private Repository

Name

RitzzStudio

---

# Environment Variables

Example

```
OPENAI_API_KEY=

ELEVENLABS_API_KEY=

PROJECT_ENV=development
```

---

# Git Ignore

```
.venv/
.env
output/
cache/
logs/
__pycache__/
*.pyc
```

---

# Development Standards

- Use type hints
- Use pathlib instead of string paths
- No hardcoded API keys
- Logging instead of print()
- Pydantic for validation
- Modular architecture
- One responsibility per module

---

# Development Workflow

```
Design

↓

Develop

↓

Test

↓

Commit

↓

Review

↓

Next Module
```

---

# Environment Checklist

## Software

- [ ] Python Installed
- [ ] VS Code Installed
- [ ] Git Installed
- [ ] FFmpeg Installed
- [ ] DaVinci Resolve Installed
- [ ] Build Tools Installed

## Accounts

- [ ] OpenAI
- [ ] ElevenLabs
- [ ] GitHub

## Project

- [ ] Repository Created
- [ ] Virtual Environment Created
- [ ] Dependencies Installed
- [ ] Environment Variables Configured
- [ ] First Commit Completed

Environment setup is complete only when every checklist item has been verified.