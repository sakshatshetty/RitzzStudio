"""Resolve the newest saved production checkpoint by project or production ID."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.production_state import PIPELINE_STAGES

PROJECT_BACKED_STAGES = frozenset(PIPELINE_STAGES[3:])
API_ROOT = "https://api.github.com"


def _github_request(
    url: str,
    token: str,
) -> Any:
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
            content = response.read()
    except (OSError, urllib.error.HTTPError) as exc:
        raise RuntimeError(f"GitHub API request failed for {url}: {exc}") from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GitHub API returned invalid JSON for {url}.") from exc


def _artifact_stage(name: str) -> tuple[str, str] | None:
    prefix = "ritzz-production-"
    if not name.startswith(prefix):
        return None
    for stage in PIPELINE_STAGES:
        suffix = f"-{stage}"
        if name.endswith(suffix):
            production_id = name[len(prefix) : -len(suffix)]
            if production_id:
                return production_id, stage
    return None


def _artifact_run_id(artifact: dict[str, Any]) -> str | None:
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict):
        return None
    run_id = workflow_run.get("id")
    return str(run_id) if run_id is not None else None


def _find_run_id_for_artifact(
    artifact: dict[str, Any],
    repository: str,
    token: str,
) -> str:
    """Find the owning workflow run when GitHub omits workflow_run on an artifact."""
    owner, separator, repo = repository.partition("/")
    if not separator or not owner or not repo:
        raise ValueError("Repository must have the owner/repository form.")

    artifact_id = int(artifact["id"])
    encoded_repo = urllib.parse.quote(f"{owner}/{repo}", safe="/")
    artifact_created_at = str(artifact.get("created_at", ""))
    page = 1
    while True:
        response = _github_request(
            f"{API_ROOT}/repos/{encoded_repo}/actions/runs"
            f"?per_page=100&page={page}",
            token,
        )
        runs = response.get("workflow_runs")
        if not isinstance(runs, list):
            raise TypeError("GitHub workflow run listing response is invalid.")

        for run in runs:
            run_id = run.get("id")
            if run_id is None:
                continue
            run_created_at = str(run.get("created_at", ""))
            if artifact_created_at and run_created_at > artifact_created_at:
                continue

            artifact_page = 1
            while True:
                run_artifacts_response = _github_request(
                    f"{API_ROOT}/repos/{encoded_repo}/actions/runs/{run_id}/artifacts"
                    f"?per_page=100&page={artifact_page}",
                    token,
                )
                run_artifacts = run_artifacts_response.get("artifacts")
                if not isinstance(run_artifacts, list):
                    raise TypeError(
                        "GitHub workflow run artifact listing response is invalid."
                    )
                if any(
                    int(run_artifact.get("id", 0)) == artifact_id
                    for run_artifact in run_artifacts
                ):
                    return str(run_id)
                if len(run_artifacts) < 100:
                    break
                artifact_page += 1

        if len(runs) < 100:
            break
        page += 1

    raise RuntimeError(
        f"Could not find the workflow run associated with artifact {artifact_id}."
    )


def _download_artifact_archive(artifact: dict[str, Any], repository: str) -> bytes:
    run_id = _artifact_run_id(artifact)
    if run_id is None:
        raise ValueError(
            f"Artifact {artifact.get('id')} has no associated workflow run."
        )
    artifact_name = str(artifact["name"])
    with tempfile.TemporaryDirectory(prefix="ritzz-checkpoint-") as directory:
        try:
            subprocess.run(
                [
                    "gh",
                    "run",
                    "download",
                    run_id,
                    "--repo",
                    repository,
                    "--name",
                    artifact_name,
                    "--dir",
                    directory,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or "No CLI error details returned.").strip()
            raise RuntimeError(
                f"GitHub CLI could not download artifact {artifact_name} "
                f"from run {run_id}: {details}"
            ) from exc

        state_files = list(Path(directory).rglob("production_state.json"))
        if len(state_files) != 1:
            raise RuntimeError(
                f"Artifact {artifact_name} must contain exactly one production_state.json; "
                f"found {len(state_files)}."
            )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("production_state.json", state_files[0].read_bytes())
        return buffer.getvalue()


def find_checkpoint_for_project(
    project_id: str,
    artifacts: list[dict[str, Any]],
    download_archive,
) -> dict[str, Any]:
    if not project_id or not project_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError(
            "Project ID must contain only letters, numbers, underscores, or hyphens."
        )
    eligible = []
    for artifact in artifacts:
        if artifact.get("expired"):
            continue
        stage_info = _artifact_stage(str(artifact.get("name", "")))
        if stage_info is not None and stage_info[1] in PROJECT_BACKED_STAGES:
            eligible.append(artifact)
    eligible.sort(
        key=lambda item: (
            str(item.get("created_at", "")),
            int(item.get("id", 0)),
        ),
        reverse=True,
    )
    for artifact in eligible:
        stage_info = _artifact_stage(str(artifact["name"]))
        if stage_info is None:
            continue
        production_id, stage = stage_info
        archive = download_archive(int(artifact["id"]))
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                state_files = [
                    name
                    for name in bundle.namelist()
                    if Path(name).name == "production_state.json"
                ]
                if not state_files:
                    raise RuntimeError(
                        f"Checkpoint artifact {artifact['name']} has no production_state.json."
                    )
                state = json.loads(bundle.read(state_files[0]))
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
            raise RuntimeError(
                f"Checkpoint artifact {artifact['name']} has invalid production state."
            ) from exc
        if state.get("production_id") != production_id:
            raise RuntimeError(
                f"Checkpoint artifact {artifact['name']} contains a different production ID."
            )
        stages = state.get("stages")
        if not isinstance(stages, dict):
            raise TypeError(
                f"Checkpoint artifact {artifact['name']} has no valid stage state."
            )
        stage_state = stages.get(stage)
        if not isinstance(stage_state, dict):
            raise TypeError(
                f"Checkpoint artifact {artifact['name']} has no state for stage {stage}."
            )
        completed_stage = stage_state.get("status") == "completed"
        failed_stage_retry = (
            stage_state.get("status") == "failed"
            and state.get("status") == "failed"
            and state.get("current_stage") == stage
            and bool(stage_state.get("artifacts"))
        )
        interrupted_private_upload = (
            stage == "private_upload"
            and stage_state.get("status") == "running"
            and state.get("current_stage") == "private_upload"
            and bool(state.get("private_upload_intent"))
        )
        if not (completed_stage or failed_stage_retry or interrupted_private_upload):
            continue
        if state.get("project_id") == project_id:
            source_run_id = _artifact_run_id(artifact)
            if source_run_id is None:
                raise RuntimeError(
                    f"Checkpoint artifact {artifact['name']} has no resolved workflow run."
                )
            return {
                "project_id": project_id,
                "production_id": production_id,
                "source_run_id": source_run_id,
                "source_artifact": str(artifact["name"]),
                "checkpoint_index": PIPELINE_STAGES.index(stage),
                "effective_mode": "RESUME",
                "matched_by": "project_id",
            }
        if state.get("production_id") == project_id:
            actual_project_id = state.get("project_id")
            if not isinstance(actual_project_id, str) or not actual_project_id:
                raise RuntimeError(
                    f"Checkpoint artifact {artifact['name']} has no valid project ID."
                )
            source_run_id = _artifact_run_id(artifact)
            if source_run_id is None:
                raise RuntimeError(
                    f"Checkpoint artifact {artifact['name']} has no resolved workflow run."
                )
            return {
                "project_id": actual_project_id,
                "production_id": production_id,
                "source_run_id": source_run_id,
                "source_artifact": str(artifact["name"]),
                "checkpoint_index": PIPELINE_STAGES.index(stage),
                "effective_mode": "RESUME",
                "matched_by": "production_id",
            }
    raise ValueError(
        "No unexpired production checkpoint was found for project ID or "
        f"production ID {project_id}."
    )


def resolve_from_github(
    project_id: str,
    repository: str,
    token: str,
) -> dict[str, Any]:
    owner, separator, repo = repository.partition("/")
    if not separator or not owner or not repo:
        raise ValueError("GITHUB_REPOSITORY must have the owner/repository form.")
    encoded_repo = urllib.parse.quote(f"{owner}/{repo}", safe="/")
    artifacts: list[dict[str, Any]] = []
    page = 1
    while True:
        response = _github_request(
            f"{API_ROOT}/repos/{encoded_repo}/actions/artifacts"
            f"?per_page=100&page={page}",
            token,
        )
        items = response.get("artifacts")
        if not isinstance(items, list):
            raise TypeError("GitHub artifact listing response is invalid.")
        artifacts.extend(items)
        if len(items) < 100:
            break
        page += 1

    def download_archive(artifact_id: int) -> bytes:
        artifact = next(
            (
                item
                for item in artifacts
                if int(item.get("id", 0)) == artifact_id
            ),
            None,
        )
        if artifact is None:
            raise RuntimeError(f"Artifact {artifact_id} disappeared from the listing.")
        if _artifact_run_id(artifact) is None:
            artifact["workflow_run"] = {
                "id": _find_run_id_for_artifact(artifact, repository, token)
            }
        return _download_artifact_archive(artifact, repository)

    return find_checkpoint_for_project(project_id, artifacts, download_archive)


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    resolved = resolve_from_github(
        project_id,
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GH_TOKEN"],
    )
    output_file = Path(os.environ["GITHUB_OUTPUT"])
    with output_file.open("a", encoding="utf-8") as output:
        for key, value in resolved.items():
            output.write(f"{key}={value}\n")
    print(json.dumps(resolved, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
