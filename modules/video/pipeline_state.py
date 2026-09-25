"""Persisted stage state for resumable video production."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

StageStatus = Literal["pending", "running", "completed", "failed"]


class PipelineStage(BaseModel):
    status: StageStatus = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    attempts: int = 0


class PipelineState(BaseModel):
    version: str = "ritzz-pipeline-state-v1"
    stages: dict[str, PipelineStage] = Field(default_factory=dict)
    current_stage: str | None = None

    def start(self, name: str) -> None:
        self.current_stage = name
        previous_attempts = self.stages.get(name, PipelineStage()).attempts
        self.stages[name] = PipelineStage(
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            attempts=previous_attempts + 1,
        )

    def complete(self, name: str) -> None:
        stage = self.stages.setdefault(name, PipelineStage())
        stage.status = "completed"
        stage.completed_at = datetime.now(timezone.utc).isoformat()
        stage.error = None
        if self.current_stage == name:
            self.current_stage = None

    def fail(self, name: str, error: str) -> None:
        stage = self.stages.setdefault(name, PipelineStage())
        stage.status = "failed"
        stage.error = error
        self.current_stage = name

    def reset_from(self, name: str, ordered_names: list[str]) -> None:
        if name not in ordered_names:
            raise ValueError(f"Unknown pipeline stage: {name}")
        for stage_name in ordered_names[ordered_names.index(name):]:
            attempts = self.stages.get(stage_name, PipelineStage()).attempts
            self.stages[stage_name] = PipelineStage(attempts=attempts)
        self.current_stage = None


def load_pipeline_state(path) -> PipelineState:
    from pathlib import Path
    file_path = Path(path)
    if not file_path.exists():
        return PipelineState()
    return PipelineState.model_validate_json(file_path.read_text(encoding="utf-8"))


def save_pipeline_state(state: PipelineState, path) -> None:
    from pathlib import Path
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
