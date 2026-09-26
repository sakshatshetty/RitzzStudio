from __future__ import annotations

import json
from pathlib import Path


CHARACTER_PROFILE_FILENAME = "character_profile.json"


def character_profile_path(project_directory: str | Path) -> Path:
    return Path(project_directory) / CHARACTER_PROFILE_FILENAME


def save_character_profile(
    project_directory: str | Path,
    profile: str,
) -> Path:
    normalized_profile = profile.strip()
    if not normalized_profile:
        raise ValueError("Character profile cannot be empty.")

    path = character_profile_path(project_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "character_profile": normalized_profile,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def load_character_profile(
    project_directory: str | Path,
) -> str | None:
    path = character_profile_path(project_directory)
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    profile = payload.get("character_profile")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError(f"Character profile is empty or invalid: {path}")
    return profile.strip()