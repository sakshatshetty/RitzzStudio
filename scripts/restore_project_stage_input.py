"""Restore the preceding project archive for a selected pipeline-stage rerun."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

STAGE_INPUTS: dict[str, tuple[str, str]] = {
    "voice_generation": ("content", "content-project.tar.gz"),
    "storyboard_generation": ("voice", "voice-project.tar.gz"),
    "image_generation": ("storyboard", "storyboard-project.tar.gz"),
    "render_video": ("image", "image-project.tar.gz"),
    "metadata_packaging": ("rendered", "rendered-project.tar.gz"),
    "private_upload": ("metadata", "rendered-project.tar.gz"),
}
API_ROOT = "https://api.github.com"


def _github_request(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GitHub Actions artifact lookup failed: {exc}") from exc


def _project_id_in_archive(archive_bytes: bytes, project_id: str) -> bool:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            project_files = [
                member
                for member in archive.getmembers()
                if member.isfile() and Path(member.name).name == "project.json"
            ]
            for member in project_files:
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                try:
                    project = json.load(stream)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if (
                    isinstance(project, dict)
                    and project.get("project_id") == project_id
                ):
                    return True
    except (tarfile.TarError, OSError):
        return False
    return False


def _download_project_artifact(
    artifact: dict[str, Any],
    repository: str,
    archive_name: str,
) -> bytes:
    run = artifact.get("workflow_run")
    if not isinstance(run, dict) or not run.get("id"):
        raise ValueError(f"Artifact {artifact.get('name')} has no workflow run ID.")
    with tempfile.TemporaryDirectory(prefix="ritzz-project-stage-") as directory:
        command = [
            "gh",
            "run",
            "download",
            str(run["id"]),
            "--repo",
            repository,
            "--name",
            str(artifact["name"]),
            "--dir",
            directory,
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            details = (
                exc.stderr or exc.stdout or "No CLI error details returned."
            ).strip()
            raise RuntimeError(
                f"Could not download project artifact {artifact['name']} "
                f"from run {run['id']}: {details}"
            ) from exc
        archives = list(Path(directory).rglob(archive_name))
        if len(archives) != 1:
            raise RuntimeError(
                f"Artifact {artifact['name']} must contain exactly one "
                "project archive; "
                f"found {len(archives)}."
            )
        return archives[0].read_bytes()


def find_project_stage_artifact(
    project_id: str,
    stage: str,
    artifacts: list[dict[str, Any]],
    download_archive: Callable[[dict[str, Any]], bytes],
) -> tuple[dict[str, Any], bytes]:
    if stage not in STAGE_INPUTS:
        raise ValueError(f"Unsupported project rerun stage: {stage}")
    if not project_id or not project_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError(
            "Project ID must contain only letters, numbers, underscores, or hyphens."
        )

    artifact_prefix, _ = STAGE_INPUTS[stage]
    candidates = sorted(
        (
            artifact
            for artifact in artifacts
            if not artifact.get("expired")
            and str(artifact.get("name", "")).startswith(
                f"ritzz-{artifact_prefix}-project-"
            )
        ),
        key=lambda item: (
            str(item.get("created_at", "")),
            int(item.get("id", 0)),
        ),
        reverse=True,
    )
    for artifact in candidates:
        archive_bytes = download_archive(artifact)
        if _project_id_in_archive(archive_bytes, project_id):
            return artifact, archive_bytes
    raise ValueError(
        f"No unexpired {artifact_prefix} project artifact was found for project ID "
        f"{project_id}; rerun stage {stage} requires that stage's saved inputs."
    )


def _list_artifacts(repository: str, token: str) -> list[dict[str, Any]]:
    owner, separator, repo = repository.partition("/")
    if not separator or not owner or not repo:
        raise ValueError("GITHUB_REPOSITORY must have the owner/repository form.")
    endpoint = urllib.parse.quote(f"{owner}/{repo}", safe="/")
    artifacts: list[dict[str, Any]] = []
    page = 1
    while True:
        response = _github_request(
            f"{API_ROOT}/repos/{endpoint}/actions/artifacts"
            f"?per_page=100&page={page}",
            token,
        )
        page_artifacts = response.get("artifacts")
        if not isinstance(page_artifacts, list):
            raise TypeError("GitHub artifact listing response is invalid.")
        artifacts.extend(page_artifacts)
        if len(page_artifacts) < 100:
            return artifacts
        page += 1


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    stage = os.environ["RITZZ_RERUN_FROM_STAGE"]
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    artifacts = _list_artifacts(repository, token)

    def download(artifact: dict[str, Any]) -> bytes:
        archive_name = STAGE_INPUTS[stage][1]
        return _download_project_artifact(artifact, repository, archive_name)

    matched_artifact, archive_bytes = find_project_stage_artifact(
        project_id,
        stage,
        artifacts,
        download,
    )
    _, archive_name = STAGE_INPUTS[stage]
    output_directory = Path(
        os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts")
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / archive_name).write_bytes(archive_bytes)
    (output_directory / "content_workflow_result.json").write_text(
        json.dumps({"project_id": project_id}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "project_id": project_id,
                "rerun_stage": stage,
                "source_run_id": matched_artifact["workflow_run"]["id"],
                "source_artifact": matched_artifact["name"],
                "restored_archive": archive_name,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
