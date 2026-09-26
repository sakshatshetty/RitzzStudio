from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


QAStatus = Literal["PASS", "REVIEW", "FAIL"]


class QAStageResult(BaseModel):
    stage: str
    status: QAStatus
    checks: dict[str, QAStatus] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    attempt: int = Field(default=1, ge=1)
    reviewer: str = "deterministic"
    reviewed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ProjectQAReport(BaseModel):
    version: str = "ritzz-project-qa-v1"
    stages: dict[str, list[QAStageResult]] = Field(default_factory=dict)

    @property
    def status(self) -> QAStatus:
        results = [attempts[-1] for attempts in self.stages.values() if attempts]
        if any(result.status == "FAIL" for result in results):
            return "FAIL"
        if any(result.status == "REVIEW" for result in results):
            return "REVIEW"
        return "PASS" if results else "REVIEW"

    def add_result(self, result: QAStageResult) -> None:
        attempts = self.stages.setdefault(result.stage, [])
        attempts.append(result.model_copy(update={"attempt": len(attempts) + 1}))
