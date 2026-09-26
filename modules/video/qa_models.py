from typing import Literal

from pydantic import BaseModel, Field


QAStatus = Literal["PASS", "REVIEW", "FAIL"]


class SceneQAResult(BaseModel):
    scene_id: str
    status: QAStatus
    narration_image: QAStatus
    narration_description: QAStatus
    editorial_context: QAStatus
    rationale: str
    correction_prompt: str | None = None
    suggested_editorial_scene_id: str | None = None


class AudioImageMatchResult(BaseModel):
    scene_id: str
    status: QAStatus
    narration: str
    start_seconds: float
    end_seconds: float
    rationale: str


class AudioImageMatchReport(BaseModel):
    results: list[AudioImageMatchResult] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {status: sum(item.status == status for item in self.results)
                for status in ("PASS", "REVIEW", "FAIL")}


class TechnicalQAResult(BaseModel):
    status: QAStatus
    checks: dict[str, QAStatus]
    issues: list[str] = Field(default_factory=list)
    scene_count: int
    audio_duration_seconds: float
    video_duration_seconds: float | None = None
    maximum_timeline_drift_seconds: float


class PilotQAReport(BaseModel):
    technical: TechnicalQAResult
    semantic_status: QAStatus = "REVIEW"
    semantic: list[SceneQAResult] = Field(default_factory=list)
