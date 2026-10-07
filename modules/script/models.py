from typing import Literal

from pydantic import BaseModel, Field

ScriptSectionType = Literal[
    "hook",
    "setup",
    "question",
    "explanation",
    "myth",
    "context",
    "payoff",
    "conclusion",
]


class ScriptSection(BaseModel):
    """A single narrated section of a Ritzz video."""

    section_id: str

    section_type: ScriptSectionType

    title: str

    narration: str = Field(
        min_length=1,
    )

    estimated_seconds: int = Field(
        ge=10,
        le=180,
    )

    research_sources: list[str] = Field(
        default_factory=list
    )


class ScriptHookPlan(BaseModel):
    modern_connection: str = ""
    modern_situation: str = ""
    modern_solution: str = ""
    shared_problem: str = ""
    ancient_problem: str = ""
    central_question: str = ""
    curiosity_question: str = ""
    open_loop: str = ""
    open_loop_description: str = ""
    stakes: str = ""
    stakes_description: str = ""
    visual_opportunity: str = ""
    first_investigation: str = ""
    modern_connection_applicable: bool = False
    quality_score: float = Field(default=0, ge=0, le=5)
    source_ids: list[str] = Field(default_factory=list)


class NarrativeMovement(BaseModel):
    section_id: str
    purpose: str
    question: str
    evidence_source_ids: list[str] = Field(default_factory=list)
    reveal: str
    next_question: str
    visual_opportunity: str


class ScriptQualityChecks(BaseModel):
    hook: Literal["PASS", "REVIEW", "FAIL"]
    hook_continuity: Literal["PASS", "REVIEW", "FAIL"]
    central_mystery: Literal["PASS", "REVIEW", "FAIL"]
    evolving_questions: Literal["PASS", "REVIEW", "FAIL"]
    section_purpose: Literal["PASS", "REVIEW", "FAIL"]
    fact_listing: Literal["PASS", "REVIEW", "FAIL"]
    evidence_integration: Literal["PASS", "REVIEW", "FAIL"]
    uncertainty: Literal["PASS", "REVIEW", "FAIL"]
    viewer_connection: Literal["PASS", "REVIEW", "FAIL"]
    final_payoff: Literal["PASS", "REVIEW", "FAIL"]
    visualizability: Literal["PASS", "REVIEW", "FAIL"]
    originality: Literal["PASS", "REVIEW", "FAIL"]


class ScriptQualityFinding(BaseModel):
    category: Literal[
        "HOOK_WEAK",
        "NO_OPEN_LOOP",
        "FACT_LISTING",
        "WEAK_EVIDENCE",
        "NO_PAYOFF",
        "POOR_VISUALIZABILITY",
        "UNSUPPORTED_CLAIM",
        "UNCERTAINTY_LOST",
        "WEAK_VIEWER_CONNECTION",
        "OTHER",
    ]
    section_ids: list[str] = Field(min_length=1)
    rationale: str
    revision_instruction: str
    research_source_ids: list[str] = Field(default_factory=list)


class ScriptQualityReview(BaseModel):
    status: Literal["PASS", "REVIEW", "FAIL"]
    checks: ScriptQualityChecks
    findings: list[ScriptQualityFinding] = Field(default_factory=list)


class ScriptSectionRevision(BaseModel):
    section_id: str
    narration: str = Field(min_length=1)
    movement: NarrativeMovement
    hook: str = ""
    hook_plan: ScriptHookPlan = Field(default_factory=ScriptHookPlan)
    viewer_connection: str = ""
    myth_or_assumption: str = ""
    uncertainty: str = ""


class Script(BaseModel):
    """Complete narration script for a Ritzz video."""

    topic: str

    target_duration_seconds: int = 480

    target_word_count: int = Field(
        ge=1,
        le=2000,
    )

    hook: str = Field(
        min_length=1,
    )

    sections: list[ScriptSection] = Field(
        default_factory=list
    )

    total_estimated_seconds: int

    total_word_count: int

    closing_message: str = Field(
        min_length=1,
    )

    script_profile: str = ""
    user_supplied: bool = False
    input_fingerprint: str = ""
    hook_plan: ScriptHookPlan = Field(default_factory=ScriptHookPlan)
    narrative_arc: list[NarrativeMovement] = Field(default_factory=list)
    viewer_connection: str = ""
    myth_or_assumption: str = ""
    major_reveals: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    visual_opportunities: list[str] = Field(default_factory=list)
    final_payoff: str = ""