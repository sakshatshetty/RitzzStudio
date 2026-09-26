from pathlib import Path

import pytest

from modules.image.character_profile import (
    character_profile_path,
    load_character_profile,
    save_character_profile,
)


def test_character_profile_is_saved_and_loaded_per_project(tmp_path: Path):
    profile = "A blue-coated stickman explorer with a round hat."

    path = save_character_profile(tmp_path, f"  {profile}  ")

    assert path == character_profile_path(tmp_path)
    assert load_character_profile(tmp_path) == profile
    assert '"version": 1' in path.read_text(encoding="utf-8")


def test_missing_character_profile_is_backward_compatible(tmp_path: Path):
    assert load_character_profile(tmp_path) is None


def test_empty_character_profile_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="cannot be empty"):
        save_character_profile(tmp_path, "  ")


def test_invalid_character_profile_artifact_is_rejected(tmp_path: Path):
    character_profile_path(tmp_path).write_text(
        '{"character_profile": ""}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="empty or invalid"):
        load_character_profile(tmp_path)