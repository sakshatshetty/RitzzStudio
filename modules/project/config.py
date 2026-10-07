"""Project-level production configuration."""

from pydantic import BaseModel, Field, model_validator

DURATION_TOLERANCE_SECONDS = 60
DEFAULT_HOOK_QUALITY_WEIGHTS = {
    "curiosity": 0.12,
    "problem_clarity": 0.12,
    "modern_relevance": 0.12,
    "ancient_connection": 0.12,
    "open_loop": 0.12,
    "specificity": 0.09,
    "factual_support": 0.10,
    "visual_potential": 0.06,
    "conversational_quality": 0.05,
    "surprise": 0.03,
    "stakes": 0.02,
    "story_continuity": 0.05,
}


class ProductionConfig(BaseModel):
    target_duration_seconds: int = Field(default=480, ge=1)
    minimum_duration_seconds: int = Field(default=480, ge=1)
    words_per_minute: int = Field(default=140, ge=80, le=220)
    script_profile: str = "RITZZ_ANCIENT_HUMAN_CURIOSITY"
    scene_minimum_duration_seconds: float = Field(default=3.0, ge=3.0)
    scene_maximum_duration_seconds: float = Field(default=4.0, gt=0, le=4.0)
    constraints: list[str] = Field(default_factory=list)
    hook_quality_weights: dict[str, float] = Field(
        default_factory=lambda: DEFAULT_HOOK_QUALITY_WEIGHTS.copy()
    )

    @model_validator(mode="after")
    def validate_durations(self):
        if self.minimum_duration_seconds > self.target_duration_seconds:
            raise ValueError("minimum_duration_seconds cannot exceed target_duration_seconds")
        if self.scene_minimum_duration_seconds > self.scene_maximum_duration_seconds:
            raise ValueError("scene minimum cannot exceed scene maximum")
        unknown_hook_dimensions = set(self.hook_quality_weights) - set(
            DEFAULT_HOOK_QUALITY_WEIGHTS
        )
        if unknown_hook_dimensions:
            raise ValueError(
                "hook_quality_weights contains unsupported dimensions: "
                + ", ".join(sorted(unknown_hook_dimensions))
            )
        if not self.hook_quality_weights or any(
            weight < 0 for weight in self.hook_quality_weights.values()
        ) or not any(
            dimension != "modern_relevance" and weight > 0
            for dimension, weight in self.hook_quality_weights.items()
        ):
            raise ValueError(
                "hook_quality_weights must contain non-negative weights with "
                "at least one positive topic-independent dimension."
            )
        return self

    @property
    def minimum_word_count(self) -> int:
        return max(1, round(self.minimum_duration_seconds * self.words_per_minute / 60))

    @property
    def minimum_acceptable_duration_seconds(self) -> int:
        return max(
            self.minimum_duration_seconds,
            self.target_duration_seconds - DURATION_TOLERANCE_SECONDS,
        )

    @property
    def maximum_acceptable_duration_seconds(self) -> int:
        return self.target_duration_seconds + DURATION_TOLERANCE_SECONDS
