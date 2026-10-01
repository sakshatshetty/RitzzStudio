import io
import json
import zipfile

import pytest

from modules.production_state import PIPELINE_STAGES
from scripts import resolve_production_by_project
from scripts.resolve_production_by_project import find_checkpoint_for_project


def checkpoint_archive(production_id: str, project_id: str) -> bytes:
    state = {
        "production_id": production_id,
        "project_id": project_id,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "production_state.json",
            json.dumps(state),
        )
    return buffer.getvalue()


def make_artifact(production_id, stage, artifact_id, created_at, run_id):
    return {
        "id": artifact_id,
        "name": f"ritzz-production-{production_id}-{stage}",
        "expired": False,
        "created_at": created_at,
        "workflow_run": {"id": run_id},
    }


def test_resolves_latest_checkpoint_by_project_id_and_ignores_expired(tmp_path):
    artifacts = [
        make_artifact("old-prod", "render_video", 1, "2026-09-30T12:00:00Z", 10),
        make_artifact("current-prod", "private_upload", 2, "2026-10-01T12:00:00Z", 11),
        {
            **make_artifact("expired-prod", "private_upload", 3, "2026-10-02T12:00:00Z", 12),
            "expired": True,
        },
    ]
    archives = {
        1: checkpoint_archive("old-prod", "PROJECT_1"),
        2: checkpoint_archive("current-prod", "PROJECT_2"),
    }
    result = find_checkpoint_for_project(
        "PROJECT_2",
        artifacts,
        lambda artifact_id: archives[artifact_id],
    )

    assert result == {
        "project_id": "PROJECT_2",
        "production_id": "current-prod",
        "source_run_id": "11",
        "source_artifact": "ritzz-production-current-prod-private_upload",
        "checkpoint_index": PIPELINE_STAGES.index("private_upload"),
        "effective_mode": "RESUME",
    }


def test_project_checkpoint_resolution_fails_when_project_id_has_no_match():
    artifact = make_artifact("other-prod", "image_generation", 5, "2026-10-01T12:00:00Z", 13)

    with pytest.raises(ValueError, match="No unexpired production checkpoint"):
        find_checkpoint_for_project(
            "missing-project",
            [artifact],
            lambda _artifact_id: checkpoint_archive("other-prod", "other-project"),
        )


def test_github_request_authenticates_with_provided_token(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(
        resolve_production_by_project.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    assert resolve_production_by_project._github_request(
        "https://api.github.com/test",
        "test-token",
    ) == {"ok": True}
    assert captured["authorization"] == "Bearer test-token"
    assert captured["timeout"] == 60
