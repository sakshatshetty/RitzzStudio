from typing import Literal

from pydantic import BaseModel, Field

from modules.storyboard.editorial_qa import EditorialCalloutQAResult
from modules.storyboard.models import CalloutPosition
from modules.storyboard.visual_models import VisualFailureCategory

QAStatus = Literal["PASS", "REVIEW", "FAIL"]


class SceneQAResult(BaseModel):
    scene_id: str
    status: QAStatus
    narration_image: QAStatus
    narration_description: QAStatus
    unwanted_text: QAStatus = "PASS"
    editorial_context: QAStatus = "PASS"
    editorial_text: QAStatus = "PASS"
    editorial_style: QAStatus = "PASS"
    editorial_placement: QAStatus = "PASS"
    editorial_obstruction: QAStatus = "PASS"
    editorial_safe_space: QAStatus = "PASS"
    rationale: str
    correction_prompt: str | None = None
    suggested_editorial_scene_id: str | None = None
    suggested_editorial_position: CalloutPosition | None = None
    failure_category: VisualFailureCategory | None = None


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


class RenderedVideoSemanticQAReport(BaseModel):
    status: QAStatus
    results: list[SceneQAResult] = Field(default_factory=list)
    sample_policy: str = "One rendered frame at each scene midpoint."

    @property
    def counts(self) -> dict[str, int]:
        return {
            status: sum(item.status == status for item in self.results)
            for status in ("PASS", "REVIEW", "FAIL")
        }


class TechnicalQAResult(BaseModel):
    status: QAStatus
    checks: dict[str, QAStatus]
    issues: list[str] = Field(default_factory=list)
    scene_count: int
    audio_duration_seconds: float
    video_duration_seconds: float | None = None
    maximum_timeline_drift_seconds: float
    integrated_lufs: float | None = None
    true_peak_dbtp: float | None = None
    target_lufs: float = -14.0
    true_peak_ceiling_dbtp: float = -1.0
    editorial_callouts: EditorialCalloutQAResult | None = None


class PilotQAReport(BaseModel):
    technical: TechnicalQAResult
    semantic_status: QAStatus = "REVIEW"
    semantic: list[SceneQAResult] = Field(default_factory=list)
