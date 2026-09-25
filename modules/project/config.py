"""Project-level production configuration."""

from pydantic import BaseModel, Field, model_validator


class ProductionConfig(BaseModel):
    target_duration_seconds: int = Field(default=480, ge=1)
    minimum_duration_seconds: int = Field(default=480, ge=1)
    words_per_minute: int = Field(default=140, ge=80, le=220)
    scene_minimum_duration_seconds: float = Field(default=3.0, gt=0)
    scene_maximum_duration_seconds: float = Field(default=30.0, gt=0)
    constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_durations(self):
        if self.minimum_duration_seconds > self.target_duration_seconds:
            raise ValueError("minimum_duration_seconds cannot exceed target_duration_seconds")
        if self.scene_minimum_duration_seconds > self.scene_maximum_duration_seconds:
            raise ValueError("scene minimum cannot exceed scene maximum")
        return self

    @property
    def minimum_word_count(self) -> int:
        return max(1, round(self.minimum_duration_seconds * self.words_per_minute / 60))
