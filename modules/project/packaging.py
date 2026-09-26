from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modules.project.manager import ProjectManager
from modules.project.models import Project


@dataclass
class TitleOption:
    title: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TitleOption":
        return cls(title=data["title"], reason=data.get("reason", ""))


@dataclass
class PackagingMetadata:
    category: str = "Education"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    thumbnail_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "description": self.description,
            "tags": self.tags,
            "thumbnail_notes": self.thumbnail_notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PackagingMetadata":
        return cls(
            category=data.get("category", "Education"),
            description=data.get("description", ""),
            tags=list(data.get("tags", [])),
            thumbnail_notes=data.get("thumbnail_notes", ""),
        )


@dataclass
class ThumbnailBrief:
    subject: str
    primary_visual: str
    text_layout: str
    mobile_readability: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "primary_visual": self.primary_visual,
            "text_layout": self.text_layout,
            "mobile_readability": self.mobile_readability,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThumbnailBrief":
        return cls(
            subject=data.get("subject", ""),
            primary_visual=data.get("primary_visual", ""),
            text_layout=data.get("text_layout", ""),
            mobile_readability=data.get("mobile_readability", ""),
            notes=data.get("notes", ""),
        )


@dataclass
class PackagingArtifact:
    selected_title: str
    title_options: list[TitleOption] = field(default_factory=list)
    metadata: PackagingMetadata = field(default_factory=PackagingMetadata)
    thumbnail_brief: ThumbnailBrief | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_title": self.selected_title,
            "title_options": [option.to_dict() for option in self.title_options],
            "metadata": self.metadata.to_dict(),
            "thumbnail_brief": self.thumbnail_brief.to_dict() if self.thumbnail_brief else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PackagingArtifact":
        return cls(
            selected_title=data.get("selected_title", ""),
            title_options=[TitleOption.from_dict(item) for item in data.get("title_options", [])],
            metadata=PackagingMetadata.from_dict(data.get("metadata", {})),
            thumbnail_brief=(
                ThumbnailBrief.from_dict(data["thumbnail_brief"])
                if isinstance(data.get("thumbnail_brief"), dict)
                else None
            ),
        )


class PackagingEngine:
    """Generate and persist title, thumbnail, and metadata packaging artifacts."""

    def __init__(self, projects_dir: str | Path):
        self.projects_dir = Path(projects_dir)

    @staticmethod
    def _normalized_topic(topic: str) -> str:
        cleaned = re.sub(r"\s+", " ", topic or "").strip()
        cleaned = re.sub(r"\?+$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _title_case_topic(topic: str) -> str:
        title = PackagingEngine._normalized_topic(topic)
        if not title:
            return "Untitled Video"
        if title.endswith("?"):
            title = title[:-1]
        return title[:1].upper() + title[1:]

    def generate_title_options(self, topic: str, script_excerpt: str) -> list[TitleOption]:
        """Create a small set of candidate titles with reasoning."""
        normalized = self._normalized_topic(topic)
        base = normalized
        if re.match(r"^(why|what|how|when|where|who)\b", base, flags=re.IGNORECASE):
            base = re.sub(r"^(why|what|how|when|where|who)\b\s*", "", base, flags=re.IGNORECASE)
        base = base.strip()
        if not base:
            base = "This Curiosity"

        script_hint = ""
        excerpt = re.sub(r"\s+", " ", script_excerpt or "").strip()
        if excerpt:
            for phrase in ["medical", "science", "surprising", "practical", "mistake", "history", "truth"]:
                if phrase.lower() in excerpt.lower():
                    script_hint = phrase
                    break

        twist = "The Surprising Reason" if script_hint else "The Practical Truth"
        structure = [
            f"{self._title_case_topic(topic)} {twist}",
            f"{self._title_case_topic(base)}: What They Didn't Tell You",
            f"{self._title_case_topic(base)} Explained in One Minute",
        ]

        unique = []
        seen = set()
        for idx, title in enumerate(structure):
            cleaned = re.sub(r"\s+", " ", title).strip()
            if not cleaned:
                continue
            lowered = cleaned.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            reason = {
                0: "Focuses on the strongest explanatory hook from the script.",
                1: "Presents a clear curiosity angle with a simple, memorable payoff.",
                2: "Keeps the title accessible and search-friendly for curious viewers.",
            }[idx]
            unique.append(TitleOption(title=cleaned, reason=reason))

        if len(unique) < 3:
            fallback = [
                f"{self._title_case_topic(base)}: The Story Behind It",
                f"Why {self._title_case_topic(base)} Matters",
                f"{self._title_case_topic(base)} Explained",
            ]
            for title in fallback:
                lowered = title.casefold()
                if not any(option.title.casefold() == lowered for option in unique):
                    unique.append(TitleOption(title=title, reason="Adds a curiosity-first framing without copying competitor wording."))

        return unique[:3]

    @staticmethod
    def _build_tags(topic: str, script_excerpt: str) -> list[str]:
        text = f"{topic} {script_excerpt}".lower()
        tokens = re.findall(r"[a-z0-9][a-z0-9'/-]{2,}", text)
        filtered = []
        for token in tokens:
            if token in {"why", "what", "how", "the", "they", "this", "that", "with", "from", "into", "about", "were", "your", "their", "then", "have", "been", "will", "just", "there", "through", "it", "its", "did", "does"}:
                continue
            if len(token) < 4:
                continue
            if token not in filtered:
                filtered.append(token)
        if len(filtered) < 4:
            filtered.extend(["curiosity", "history", "explainer", "facts"])
        return filtered[:8]

    @staticmethod
    def _keyword_tokens(text: str) -> set[str]:
        return {
            token for token in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(token) > 2 and token not in {"with", "that", "this", "they", "them", "from", "into", "about", "what", "when", "where", "why", "how", "tells", "story", "their", "your", "there", "then", "than", "have", "been", "will", "just", "could", "should"}
        }

    def validate_packaging_metadata(
        self,
        topic: str,
        selected_title: str,
        description: str,
        tags: list[str],
    ) -> dict[str, Any]:
        topic_words = self._keyword_tokens(topic)
        title_words = self._keyword_tokens(selected_title)
        description_words = self._keyword_tokens(description)
        tag_words = self._keyword_tokens(" ".join(tags or []))

        overlap = topic_words & (title_words | description_words | tag_words)
        if not overlap:
            raise ValueError(
                "Selected title and metadata do not reflect the approved topic; packaging must stay truthful to the chosen subject."
            )

        return {
            "status": "PASS",
            "issues": [],
            "topic_overlap": sorted(overlap),
        }

    def generate_thumbnail_brief(
        self,
        project: Project,
        topic: str,
        selected_title: str,
        script_excerpt: str,
    ) -> ThumbnailBrief:
        normalized = self._normalized_topic(topic)
        if "pirate" in normalized.lower() and "eye" in normalized.lower():
            subject = "Pirate eye patch + sunlight contrast"
            primary_visual = "A pirate with one eye covered, the other eye staring into bright sunlight while the dark deck is visible in the background."
        else:
            subject = self._title_case_topic(topic)
            primary_visual = f"A highly recognizable object tied to the topic, framed with a clean, single-idea visual and strong contrast."

        brief = ThumbnailBrief(
            subject=subject,
            primary_visual=primary_visual,
            text_layout="Use a bold two-line headline centered near the top, with no more than 3 words of secondary text.",
            mobile_readability="Keep the focal object large and readable on mobile: high contrast, clear silhouette, text no more than 2 lines and large enough to read without zooming.",
            notes=(
                f"Selected title: {selected_title}. "
                f"Use the strongest single hook from the script: {script_excerpt.strip()[:160]}"
            ),
        )
        return brief

    def select_title(self, project: Project, selected_title: str) -> str:
        if not selected_title or not selected_title.strip():
            raise ValueError("A selected title is required.")

        project_path = Path(self.projects_dir) / f"{project.project_id}_{project.slug}"
        packaging_path = project_path / "packaging.json"
        if not packaging_path.exists():
            raise FileNotFoundError(f"No packaging file found for project {project.project_id}")

        artifact = PackagingArtifact.from_dict(json.loads(packaging_path.read_text(encoding="utf-8")))
        artifact.selected_title = selected_title.strip()
        if not artifact.title_options:
            artifact.title_options = self.generate_title_options(project.title, "")
        packaging_path.write_text(json.dumps(artifact.to_dict(), indent=2), encoding="utf-8")

        project.steps["packaging"] = True
        project.status = "packaging_title_selected"
        ProjectManager(self.projects_dir)._save_project(project, project_path)
        return artifact.selected_title

    def build_project_packaging(
        self,
        project: Project,
        topic: str,
        script_excerpt: str,
        selected_title: str | None = None,
    ) -> PackagingArtifact:
        project_path = Path(self.projects_dir) / f"{project.project_id}_{project.slug}"
        title_options = self.generate_title_options(topic, script_excerpt)
        chosen = (selected_title or title_options[0].title).strip()

        description = (
            f"{chosen}. "
            f"{script_excerpt.strip()[:220]}"
            if script_excerpt.strip()
            else f"A curious explainer about {topic}."
        )
        tags = self._build_tags(topic, script_excerpt)
        self.validate_packaging_metadata(topic, chosen, description, tags)
        metadata = PackagingMetadata(
            category="Education",
            description=description,
            tags=tags,
            thumbnail_notes=(
                "Use a clean, high-contrast thumbnail with a single visual hook, clear readable text, "
                "and one dominant object so it remains legible on mobile."
            ),
        )
        thumbnail_brief = self.generate_thumbnail_brief(project, topic, chosen, script_excerpt)
        artifact = PackagingArtifact(
            selected_title=chosen,
            title_options=title_options,
            metadata=metadata,
            thumbnail_brief=thumbnail_brief,
        )

        project_file = project_path / "packaging.json"
        project_file.write_text(json.dumps(artifact.to_dict(), indent=2), encoding="utf-8")

        project.steps.setdefault("packaging", True)
        project.status = "packaging_complete"
        ProjectManager(self.projects_dir)._save_project(project, project_path)
        return artifact

    @staticmethod
    def load_project_packaging(project_path: str | Path) -> PackagingArtifact:
        path = Path(project_path) / "packaging.json"
        if not path.exists():
            raise FileNotFoundError(f"No packaging artifact found at {path}")
        return PackagingArtifact.from_dict(json.loads(path.read_text(encoding="utf-8")))
