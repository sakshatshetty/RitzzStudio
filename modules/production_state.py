"""Persistent state and artifact validation for resumable pipeline productions."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_VERSION = 1
PIPELINE_STAGES = (
    "topic_discovery",
    "topic_selection",
    "content_preparation",
    "voice_generation",
    "storyboard_generation",
    "image_generation",
    "render_video",
    "private_upload",
)
_PRODUCTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


class ProductionStateError(RuntimeError):
    """A production state or its persisted artifacts are invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class ProductionStateStore:
    """Read and update a production state document beside pipeline artifacts."""

    def __init__(self, state_file: str | Path, artifact_root: str | Path | None = None):
        self.state_file = Path(state_file)
        self.artifact_root = (
            Path(artifact_root) if artifact_root else self.state_file.parent
        )

    def initialize(self, production_id: str) -> dict[str, Any]:
        self._validate_production_id(production_id)
        if self.state_file.exists():
            raise ProductionStateError(
                "PRODUCTION_ALREADY_EXISTS",
                f"State already exists at {self.state_file}.",
            )
        now = self._now()
        state: dict[str, Any] = {
            "state_version": STATE_VERSION,
            "production_id": production_id,
            "project_id": None,
            "status": "in_progress",
            "current_stage": None,
            "created_at": now,
            "updated_at": now,
            "approval_issue_number": None,
            "private_upload_intent": None,
            "stages": {
                stage: {
                    "status": "pending",
                    "attempts": 0,
                    "started_at": None,
                    "completed_at": None,
                    "error": None,
                    "artifacts": [],
                }
                for stage in PIPELINE_STAGES
            },
        }
        self._save(state)
        return state

    def resume(self, production_id: str) -> dict[str, Any]:
        self._validate_production_id(production_id)
        if not self.state_file.is_file():
            raise ProductionStateError(
                "PRODUCTION_NOT_FOUND",
                f"No persisted state was found at {self.state_file}.",
            )
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                f"Production state could not be read: {exc}",
            ) from exc
        self._validate_state(state, production_id)
        self._validate_artifacts(state)
        self._validate_artifact_contracts(state)
        return state

    def start_stage(self, stage: str) -> dict[str, Any]:
        state = self._read_state()
        stage_state = self._stage(state, stage)
        stage_state.update(
            status="running",
            attempts=stage_state["attempts"] + 1,
            started_at=self._now(),
            completed_at=None,
            error=None,
        )
        state["current_stage"] = stage
        state["status"] = "in_progress"
        self._save(state)
        return state

    def set_project_id(self, project_id: str) -> dict[str, Any]:
        if not project_id:
            raise ValueError("Project ID cannot be empty.")
        state = self._read_state()
        if state.get("current_stage") != "content_preparation":
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                "A project ID can only be set during content preparation.",
            )
        existing_project_id = state.get("project_id")
        if existing_project_id not in (None, project_id):
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                "Project ID does not match the existing production project.",
            )
        state["project_id"] = project_id
        self._save(state)
        return state

    def complete_stage(
        self,
        stage: str,
        artifact_paths: Iterable[str | Path] = (),
        project_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._read_state()
        stage_state = self._stage(state, stage)
        if state.get("current_stage") != stage or stage_state["status"] != "running":
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                f"Cannot complete stage {stage} because it is not the active stage.",
            )
        artifacts = [self._artifact_record(path) for path in artifact_paths]
        if not artifacts:
            raise ValueError(
                f"Completed stage {stage} must record at least one artifact."
            )
        stage_state.update(
            status="completed",
            completed_at=self._now(),
            error=None,
            artifacts=artifacts,
        )
        state["current_stage"] = None
        if project_id is not None:
            state["project_id"] = project_id
        state["status"] = (
            "completed"
            if all(item["status"] == "completed" for item in state["stages"].values())
            else "in_progress"
        )
        self._save(state)
        return state

    def fail_stage(
        self,
        stage: str,
        error: str,
        artifact_paths: Iterable[str | Path] = (),
        project_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._read_state()
        stage_state = self._stage(state, stage)
        if state.get("current_stage") == stage and stage_state["status"] == "failed":
            return state
        if state.get("current_stage") != stage or stage_state["status"] != "running":
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                f"Cannot fail stage {stage} because it is not the active stage.",
            )
        artifacts = [self._artifact_record(path) for path in artifact_paths]
        stage_state.update(
            status="failed",
            error=error,
            completed_at=None,
            artifacts=artifacts,
        )
        state["current_stage"] = stage
        state["status"] = "failed"
        if project_id is not None:
            state["project_id"] = project_id
        self._save(state)
        return state

    def set_approval_issue(self, issue_number: int) -> dict[str, Any]:
        if issue_number < 1:
            raise ValueError("Approval issue number must be positive.")
        state = self._read_state()
        state["approval_issue_number"] = issue_number
        self._save(state)
        return state

    def set_private_upload_intent(
        self, run_id: str, run_attempt: int
    ) -> dict[str, Any]:
        state = self._read_state()
        if state.get("current_stage") != "private_upload":
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                "Private upload intent can only be recorded while that stage is running.",
            )
        intent = state.get("private_upload_intent")
        if intent is not None:
            raise ProductionStateError(
                "PUBLISH_ATTEMPT_RECONCILIATION_REQUIRED",
                "A private upload intent already exists; reconcile it before another upload.",
            )
        if not run_id or run_attempt < 1:
            raise ValueError("A GitHub run ID and positive run attempt are required.")
        state["private_upload_intent"] = {
            "run_id": run_id,
            "run_attempt": run_attempt,
            "created_at": self._now(),
        }
        self._save(state)
        return state

    def validate_private_upload_intent(self, run_id: str, run_attempt: int) -> None:
        state = self._read_state()
        intent = state.get("private_upload_intent")
        if (
            not isinstance(intent, dict)
            or intent.get("run_id") != run_id
            or intent.get("run_attempt") != run_attempt
        ):
            raise ProductionStateError(
                "PUBLISH_ATTEMPT_RECONCILIATION_REQUIRED",
                "The saved upload intent belongs to another workflow attempt. "
                "Check YouTube before authorizing another upload.",
            )

    def _read_state(self) -> dict[str, Any]:
        if not self.state_file.is_file():
            raise ProductionStateError(
                "PRODUCTION_NOT_FOUND",
                f"No persisted state was found at {self.state_file}.",
            )
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                f"Production state could not be read: {exc}",
            ) from exc
        if not isinstance(state, dict) or state.get("state_version") != STATE_VERSION:
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                "Production state has an unsupported or invalid schema.",
            )
        self._validate_state(state, str(state.get("production_id", "")))
        return state

    def _validate_state(self, state: Any, production_id: str) -> None:
        if (
            not isinstance(state, dict)
            or state.get("state_version") != STATE_VERSION
            or state.get("production_id") != production_id
            or not isinstance(state.get("stages"), dict)
            or any(stage not in state["stages"] for stage in PIPELINE_STAGES)
            or state.get("status") not in {"in_progress", "failed", "completed"}
            or state.get("current_stage") not in (None, *PIPELINE_STAGES)
            or state.get("project_id") is not None
            and not isinstance(state.get("project_id"), str)
            or state.get("approval_issue_number") is not None
            and not isinstance(state.get("approval_issue_number"), int)
            or state.get("private_upload_intent") is not None
            and not isinstance(state.get("private_upload_intent"), dict)
        ):
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                "State schema or production ID does not match the requested production.",
            )
        valid_statuses = {"pending", "running", "completed", "failed"}
        for stage in PIPELINE_STAGES:
            stage_state = state["stages"][stage]
            if (
                not isinstance(stage_state, dict)
                or stage_state.get("status") not in valid_statuses
                or not isinstance(stage_state.get("artifacts"), list)
                or not isinstance(stage_state.get("attempts"), int)
            ):
                raise ProductionStateError(
                    "STATE_ARTIFACT_MISMATCH",
                    f"Invalid stage state for {stage}.",
                )

    def _validate_artifacts(self, state: dict[str, Any]) -> None:
        for stage in PIPELINE_STAGES:
            stage_state = state["stages"][stage]
            if not isinstance(stage_state, dict):
                raise ProductionStateError(
                    "STATE_ARTIFACT_MISMATCH",
                    f"Invalid stage record for {stage}.",
                )
            artifacts = stage_state.get("artifacts")
            if stage_state.get("status") == "completed" and not artifacts:
                raise ProductionStateError(
                    "STATE_ARTIFACT_MISMATCH",
                    f"Completed stage {stage} has no artifact manifest.",
                )
            if not artifacts:
                continue
            if not isinstance(artifacts, list):
                raise ProductionStateError(
                    "STATE_ARTIFACT_MISMATCH",
                    f"Invalid artifact manifest for stage {stage}.",
                )
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    raise ProductionStateError(
                        "STATE_ARTIFACT_MISMATCH",
                        f"Invalid artifact entry for stage {stage}.",
                    )
                relative_path = Path(str(artifact.get("path", "")))
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise ProductionStateError(
                        "STATE_ARTIFACT_MISMATCH",
                        f"Unsafe artifact path in stage {stage}.",
                    )
                path = self.artifact_root / relative_path
                try:
                    path.resolve().relative_to(self.artifact_root.resolve())
                except ValueError as exc:
                    raise ProductionStateError(
                        "STATE_ARTIFACT_MISMATCH",
                        f"Artifact path escapes the artifact root: {relative_path}.",
                    ) from exc
                if not path.is_file() or self._sha256(path) != artifact.get("sha256"):
                    raise ProductionStateError(
                        "STATE_ARTIFACT_MISMATCH",
                        f"Artifact missing or changed for stage {stage}: {relative_path}.",
                    )

    def _validate_artifact_contracts(self, state: dict[str, Any]) -> None:
        try:
            if state["stages"]["topic_selection"]["status"] == "completed":
                candidates = json.loads(
                    (self.artifact_root / "topic_candidates.json").read_text(
                        encoding="utf-8"
                    )
                )
                selection = json.loads(
                    (self.artifact_root / "topic_selection.json").read_text(
                        encoding="utf-8"
                    )
                )
                selected = next(
                    (
                        candidate
                        for candidate in candidates.get("candidates", [])
                        if candidate.get("candidate_id")
                        == selection.get("candidate_id")
                    ),
                    None,
                )
                if selected is None or selected.get("topic") != selection.get("topic"):
                    raise ValueError(
                        "Selected candidate does not match the discovery artifact."
                    )

            if (
                state.get("project_id")
                and state["stages"]["content_preparation"]["status"] == "completed"
            ):
                result = json.loads(
                    (self.artifact_root / "content_workflow_result.json").read_text(
                        encoding="utf-8"
                    )
                )
                if result.get("project_id") != state["project_id"]:
                    raise ValueError(
                        "Content result project ID does not match production state."
                    )
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ProductionStateError(
                "STATE_ARTIFACT_MISMATCH",
                f"Production artifacts do not satisfy their recorded contract: {exc}",
            ) from exc

    def _artifact_record(self, path: str | Path) -> dict[str, str]:
        artifact_path = Path(path)
        if not artifact_path.is_absolute():
            artifact_path = self.artifact_root / artifact_path
        try:
            relative_path = artifact_path.resolve().relative_to(
                self.artifact_root.resolve()
            )
        except ValueError as exc:
            raise ValueError(
                "Stage artifacts must be inside the artifact root."
            ) from exc
        if not artifact_path.is_file():
            raise FileNotFoundError(f"Stage artifact does not exist: {artifact_path}")
        return {"path": relative_path.as_posix(), "sha256": self._sha256(artifact_path)}

    @staticmethod
    def _stage(state: dict[str, Any], stage: str) -> dict[str, Any]:
        if stage not in PIPELINE_STAGES:
            raise ValueError(f"Unknown pipeline stage: {stage}")
        return state["stages"][stage]

    @staticmethod
    def _validate_production_id(production_id: str) -> None:
        if not _PRODUCTION_ID_PATTERN.fullmatch(production_id):
            raise ValueError(
                "Production ID must be 1–80 letters, numbers, underscores, or hyphens "
                "and start with a letter or number."
            )

    def _save(self, state: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        state["updated_at"] = self._now()
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.state_file.parent,
            delete=False,
        ) as temporary:
            json.dump(state, temporary, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(self.state_file)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
