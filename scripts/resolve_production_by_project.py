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


def _download_artifact_archive(artifact: dict[str, Any], repository: str) -> bytes:
    run_id = str(artifact["workflow_run"]["id"])
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
    eligible = [
        artifact
        for artifact in artifacts
        if not artifact.get("expired")
        and _artifact_stage(str(artifact.get("name", "")))
        and _artifact_stage(str(artifact.get("name", "")))[1]
        in PROJECT_BACKED_STAGES
    ]
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
        if state.get("project_id") == project_id:
            return {
                "project_id": project_id,
                "production_id": production_id,
                "source_run_id": str(artifact["workflow_run"]["id"]),
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
            return {
                "project_id": actual_project_id,
                "production_id": production_id,
                "source_run_id": str(artifact["workflow_run"]["id"]),
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
