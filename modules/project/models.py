from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Project:
    project_id: str
    title: str
    slug: str
    status: str = "created"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    steps: dict[str, bool] = field(
        default_factory=lambda: {
            "research": False,
            "outline": False,
            "script": False,
            "storyboard": False,
            "images": False,
            "voice": False,
            "video": False,
            "thumbnail": False,
        }
    )

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "slug": self.slug,
            "status": self.status,
            "created_at": self.created_at,
            "steps": self.steps,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        return cls(
            project_id=data["project_id"],
            title=data["title"],
            slug=data["slug"],
            status=data.get("status", "created"),
            created_at=data["created_at"],
            steps=data.get("steps", {}),
        )