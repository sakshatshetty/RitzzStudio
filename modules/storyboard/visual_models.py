from typing import Literal

from pydantic import BaseModel, Field

ScenePurpose = Literal[
    "ESTABLISH",
    "EXPLAIN",
    "SHOW_PROCESS",
    "COMPARE",
    "EVIDENCE",
    "CONSEQUENCE",
    "REVEAL",
    "EXAMPLE",
    "TRANSITION",
    "SUMMARY",
]

VisualFailureCategory = Literal[
    "ANACHRONISM",
    "AMBIGUITY",
    "WRONG_ACTION",
    "WRONG_ENVIRONMENT",
    "MISSING_REQUIRED_OBJECT",
    "FORBIDDEN_OBJECT",
    "CHARACTER_CONTINUITY",
    "EDITORIAL_MISMATCH",
    "EDITORIAL_OVER_FACE",
    "EDITORIAL_OVER_CHARACTER",
    "EDITORIAL_OVER_OBJECT",
    "EDITORIAL_OVER_ACTION",
    "EDITORIAL_NO_SAFE_SPACE",
    "EDITORIAL_CLIPPED",
    "EDITORIAL_TOO_CLOSE_TO_SUBJECT",
    "EDITORIAL_POOR_CONTRAST",
    "NARRATION_MISMATCH",
    "VISUAL_DUPLICATE",
    "OTHER",
]


class VisualRestriction(BaseModel):
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    research_basis: str = ""


class VisualWorldBible(BaseModel):
    version: int = 1
    topic: str
    historical: bool
    time_period: str
    geography: str
    civilization_or_society: str
    technology_level: str
    built_environment: str
    clothing: str
    transportation: str
    tools_and_weapons: str
    containers_and_materials: str
    architecture: str
    natural_environment: str
    social_context: str
    visual_style: str
    technology_ceiling: str
    forbidden_visuals: list[VisualRestriction] = Field(default_factory=list)
    research_facts: list[str] = Field(default_factory=list)


class SceneVisualContract(BaseModel):
    scene_id: str
    purpose: ScenePurpose
    subject: str = Field(min_length=1)
    action: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    historical_context: str = Field(min_length=1)
    required_objects: list[str] = Field(default_factory=list)
    forbidden_objects: list[str] = Field(default_factory=list)
    ambiguity_resolution: str = Field(min_length=1)
    continuity_requirements: list[str] = Field(default_factory=list)
    context_transition: bool = False
    context_transition_reason: str = ""
    semantic_review_reasons: list[str] = Field(default_factory=list)


class SceneVisualContractBatch(BaseModel):
    scenes: list[SceneVisualContract]
