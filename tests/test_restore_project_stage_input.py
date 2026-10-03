import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.restore_project_stage_input import (
    STAGE_INPUTS,
    _download_project_artifact,
    _project_id_in_archive,
    find_project_stage_artifact,
)


def _project_archive(project_id: str) -> bytes:
    content = json.dumps(
        {
            "project_id": project_id,
            "title": "Project archive test",
        }
    ).encode("utf-8")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("20261001_001_project/project.json")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _artifact(stage: str, artifact_id: int, created_at: str) -> dict:
    prefix, _ = STAGE_INPUTS[stage]
    return {
        "id": artifact_id,
        "name": f"ritzz-{prefix}-project-{artifact_id}",
        "created_at": created_at,
        "expired": False,
        "workflow_run": {"id": artifact_id},
    }


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("voice_generation", ("content", "content-project.tar.gz")),
        ("storyboard_generation", ("voice", "voice-project.tar.gz")),
        ("image_generation", ("storyboard", "storyboard-project.tar.gz")),
        ("render_video", ("image", "image-project.tar.gz")),
        ("private_upload", ("rendered", "rendered-project.tar.gz")),
    ],
)
def test_stage_rerun_uses_previous_stage_project_archive(stage, expected):
    assert STAGE_INPUTS[stage] == expected


def test_project_archive_match_reads_project_id_from_metadata():
    assert _project_id_in_archive(_project_archive("20261001_001"), "20261001_001")
    assert not _project_id_in_archive(_project_archive("20261001_001"), "different")
    assert not _project_id_in_archive(b"not a tar archive", "20261001_001")


def test_download_reads_selected_stage_archive_from_source_run(tmp_path, monkeypatch):
    artifact = _artifact("render_video", 51, "2026-10-02T12:00:00Z")
    expected = b"image project archive"
    captured = {}

    def fake_run(command, *, check, capture_output, text):
        output_directory = Path(command[-1])
        output_directory.mkdir(parents=True, exist_ok=True)
        (output_directory / "content-project.tar.gz").write_bytes(b"older stage")
        (output_directory / "image-project.tar.gz").write_bytes(expected)
        captured["command"] = command
        captured["check"] = check

    monkeypatch.setattr(
        "scripts.restore_project_stage_input.subprocess.run",
        fake_run,
    )
    result = _download_project_artifact(
        artifact,
        "sakshatshetty/RitzzStudio",
        "image-project.tar.gz",
    )

    assert result == expected
    assert captured["command"][0:3] == ["gh", "run", "download"]
    assert captured["command"][3] == "51"
    assert captured["check"] is True


def test_finds_newest_unexpired_matching_project_stage_artifact():
    artifacts = [
        _artifact("render_video", 1, "2026-10-01T12:00:00Z"),
        _artifact("render_video", 2, "2026-10-02T12:00:00Z"),
        {
            **_artifact("render_video", 3, "2026-10-03T12:00:00Z"),
            "expired": True,
        },
        _artifact("image_generation", 4, "2026-10-04T12:00:00Z"),
    ]
    archives = {
        1: _project_archive("20261001_001"),
        2: _project_archive("other_project"),
        4: _project_archive("20261001_001"),
    }
    visited: list[int] = []

    artifact, archive = find_project_stage_artifact(
        "20261001_001",
        "render_video",
        artifacts,
        lambda item: visited.append(item["id"]) or archives[item["id"]],
    )

    assert artifact["id"] == 1
    assert archive == archives[1]
    assert visited == [2, 1]


def test_project_stage_restore_rejects_invalid_stage_and_missing_project():
    with pytest.raises(ValueError, match="Unsupported project rerun stage"):
        find_project_stage_artifact(
            "20261001_001",
            "content_preparation",
            [],
            lambda _: b"",
        )

    with pytest.raises(ValueError, match="No unexpired image project artifact"):
        find_project_stage_artifact(
            "20261001_001",
            "render_video",
            [_artifact("render_video", 8, "2026-10-02T12:00:00Z")],
            lambda _: _project_archive("different_project"),
        )


def test_workflow_dispatch_exposes_project_id_and_rerun_stage_inputs():
    workflow_path = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "ritzz-pipeline.yml"
    )
    workflow_text = workflow_path.read_text(encoding="utf-8")

    assert "      project_id:" in workflow_text
    assert "      rerun_from_stage:" in workflow_text
    for stage in STAGE_INPUTS:
        assert f"          - {stage}" in workflow_text
    assert "  restore-production:" in workflow_text
