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
    opportunity_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_title": self.selected_title,
            "title_options": [option.to_dict() for option in self.title_options],
            "metadata": self.metadata.to_dict(),
            "thumbnail_brief": self.thumbnail_brief.to_dict() if self.thumbnail_brief else None,
            "opportunity_context": dict(self.opportunity_context),
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
            opportunity_context=dict(data.get("opportunity_context", {})),
        )


@dataclass
class ThumbnailVariant:
    variant_name: str
    prompt: str
    text: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_name": self.variant_name,
            "prompt": self.prompt,
            "text": self.text,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThumbnailVariant":
        return cls(
            variant_name=data.get("variant_name", "A"),
            prompt=data.get("prompt", ""),
            text=data.get("text", ""),
            notes=data.get("notes", ""),
        )


@dataclass
class UploadPackage:
    final_video: str = ""
    title_variants: list[TitleOption] = field(default_factory=list)
    thumbnail_variants: list[ThumbnailVariant] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    category: str = "Education"
    language: str = "en"
    audience: dict[str, Any] = field(default_factory=lambda: {"made_for_kids": False})
    altered_synthetic_content: dict[str, Any] = field(default_factory=lambda: {
        "status": "determine_per_video",
        "disclosure": "",
        "never_blindly_mark_true": True,
    })
    chapters: dict[str, Any] = field(default_factory=lambda: {
        "allow_automatic_chapters": True,
        "generate_manual_chapters": True,
        "manual_chapters": [],
    })
    playlist: str | None = None
    end_screen_plan: dict[str, Any] = field(default_factory=dict)
    cards_plan: dict[str, Any] = field(default_factory=dict)
    comment_settings: dict[str, Any] = field(default_factory=lambda: {
        "allow_comments": True,
        "hold_potentially_inappropriate_comments": True,
        "show_like_count": True,
    })
    monetization_settings: dict[str, Any] = field(default_factory=lambda: {
        "monetized": True,
        "ad_compatibility": "standard",
    })
    upload_checklist: list[str] = field(default_factory=lambda: [
        "final video ready",
        "title approved",
        "thumbnail approved",
        "description reviewed",
        "tags reviewed",
        "category confirmed",
        "language confirmed",
        "audience confirmed",
        "synthetic content review complete",
        "manual schedule set",
        "final review complete",
    ])
    manual_review: dict[str, Any] = field(default_factory=lambda: {
        "workflow": "MANUAL UPLOAD / REVIEW / SCHEDULE",
        "upload_status": "private",
        "scheduling": "MANUAL",
        "ab_test": "MANUALLY START/CONFIRM A/B TEST",
    })
    visibility: dict[str, Any] = field(default_factory=lambda: {
        "upload_status": "private",
        "scheduling": "MANUAL",
        "embeddable": True,
        "public_statistics": True,
    })
    subtitles: dict[str, Any] = field(default_factory=lambda: {
        "generate_english_subtitles": True,
        "language": "en",
        "file": "subtitle_en.vtt",
    })
    license: str = "Standard YouTube License"
    ab_test: dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "variant_count": 3,
        "winner_required": True,
        "winner": None,
    })

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_video": self.final_video,
            "title_variants": [option.to_dict() for option in self.title_variants],
            "thumbnail_variants": [variant.to_dict() for variant in self.thumbnail_variants],
            "description": self.description,
            "tags": list(self.tags),
            "category": self.category,
            "language": self.language,
            "audience": dict(self.audience),
            "altered_synthetic_content": dict(self.altered_synthetic_content),
            "chapters": dict(self.chapters),
            "playlist": self.playlist,
            "end_screen_plan": dict(self.end_screen_plan),
            "cards_plan": dict(self.cards_plan),
            "comment_settings": dict(self.comment_settings),
            "monetization_settings": dict(self.monetization_settings),
            "upload_checklist": list(self.upload_checklist),
            "manual_review": dict(self.manual_review),
            "visibility": dict(self.visibility),
            "subtitles": dict(self.subtitles),
            "license": self.license,
            "ab_test": dict(self.ab_test),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UploadPackage":
        return cls(
            final_video=data.get("final_video", ""),
            title_variants=[TitleOption.from_dict(item) for item in data.get("title_variants", [])],
            thumbnail_variants=[ThumbnailVariant.from_dict(item) for item in data.get("thumbnail_variants", [])],
            description=data.get("description", ""),
            tags=list(data.get("tags", [])),
            category=data.get("category", "Education"),
            language=data.get("language", "en"),
            audience=dict(data.get("audience", {"made_for_kids": False})),
            altered_synthetic_content=dict(data.get("altered_synthetic_content", {
                "status": "determine_per_video",
                "never_blindly_mark_true": True,
            })),
            chapters=dict(data.get("chapters", {"allow_automatic_chapters": True, "generate_manual_chapters": True, "manual_chapters": []})),
            playlist=data.get("playlist"),
            end_screen_plan=dict(data.get("end_screen_plan", {})),
            cards_plan=dict(data.get("cards_plan", {})),
            comment_settings=dict(data.get("comment_settings", {"allow_comments": True, "hold_potentially_inappropriate_comments": True, "show_like_count": True})),
            monetization_settings=dict(data.get("monetization_settings", {"monetized": True, "ad_compatibility": "standard"})),
            upload_checklist=list(data.get("upload_checklist", [])),
            manual_review=dict(data.get("manual_review", {"workflow": "MANUAL UPLOAD / REVIEW / SCHEDULE", "upload_status": "private", "scheduling": "MANUAL"})),
            visibility=dict(data.get("visibility", {"upload_status": "private", "scheduling": "MANUAL", "embeddable": True, "public_statistics": True})),
            subtitles=dict(data.get("subtitles", {"generate_english_subtitles": True, "language": "en", "file": "subtitle_en.vtt"})),
            license=data.get("license", "Standard YouTube License"),
            ab_test=dict(data.get("ab_test", {"enabled": True, "variant_count": 3, "winner_required": True, "winner": None})),
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

    def generate_title_options(
        self,
        topic: str,
        script_excerpt: str,
        *,
        opportunity_context: dict[str, Any] | None = None,
    ) -> list[TitleOption]:
        """Create a small set of candidate titles with reasoning."""
        context = opportunity_context or {}
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
        proposed_title = str(context.get("proposed_title", "")).strip()
        if proposed_title:
            structure.insert(0, proposed_title)

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
            reason = (
                "Uses the selected vidIQ angle and proposed title as evidence."
                if proposed_title and idx == 0
                else {
                    0: "Focuses on the strongest explanatory hook from the script.",
                    1: "Presents a clear curiosity angle with a simple, memorable payoff.",
                    2: "Keeps the title accessible and search-friendly for curious viewers.",
                }.get(idx, "Provides an additional curiosity-first packaging option.")
            )
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
    def _build_tags(
        topic: str,
        script_excerpt: str,
        opportunity_context: dict[str, Any] | None = None,
    ) -> list[str]:
        context = opportunity_context or {}
        evidence_terms = [
            str(context.get("primary_keyword", "")),
            *[str(item) for item in context.get("related_keywords", [])],
            *[str(item) for item in context.get("related_questions", [])],
        ]
        text = f"{topic} {script_excerpt} {' '.join(evidence_terms)}".lower()
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
        opportunity_context: dict[str, Any] | None = None,
    ) -> ThumbnailBrief:
        normalized = self._normalized_topic(topic)
        context = opportunity_context or {}
        angle = str(context.get("angle", "")).strip()
        if "pirate" in normalized.lower() and "eye" in normalized.lower():
            subject = "Pirate eye patch + sunlight contrast"
            primary_visual = "A pirate with one eye covered, the other eye staring into bright sunlight while the dark deck is visible in the background."
        else:
            subject = self._title_case_topic(topic)
            primary_visual = f"A highly recognizable object tied to the topic, framed around {angle or 'one clear curiosity hook'} with strong contrast."

        brief = ThumbnailBrief(
            subject=subject,
            primary_visual=primary_visual,
            text_layout="Use a bold two-line headline centered near the top, with no more than 3 words of secondary text.",
            mobile_readability="Keep the focal object large and readable on mobile: high contrast, clear silhouette, text no more than 2 lines and large enough to read without zooming.",
            notes=(
                f"Selected title: {selected_title}. "
                f"Use the strongest single hook from the script: {script_excerpt.strip()[:160]} "
                f"VidIQ angle used as planning evidence: {angle or 'none'}"
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
        *,
        category: str = "Education",
        language: str = "en",
        made_for_kids: bool = False,
        opportunity_context: dict[str, Any] | None = None,
    ) -> PackagingArtifact:
        project_path = Path(self.projects_dir) / f"{project.project_id}_{project.slug}"
        context = dict(opportunity_context or {})
        title_options = self.generate_title_options(
            topic,
            script_excerpt,
            opportunity_context=context,
        )
        chosen = (selected_title or title_options[0].title).strip()

        description = (
            f"{chosen}. "
            f"{script_excerpt.strip()[:220]}"
            if script_excerpt.strip()
            else f"A curious explainer about {topic}."
        )
        tags = self._build_tags(topic, script_excerpt, context)
        self.validate_packaging_metadata(topic, chosen, description, tags)
        metadata = PackagingMetadata(
            category=category,
            description=description,
            tags=tags,
            thumbnail_notes=(
                "Use a clean, high-contrast thumbnail with a single visual hook, clear readable text, "
                "and one dominant object so it remains legible on mobile."
            ),
        )
        thumbnail_brief = self.generate_thumbnail_brief(
            project,
            topic,
            chosen,
            script_excerpt,
            context,
        )
        artifact = PackagingArtifact(
            selected_title=chosen,
            title_options=title_options,
            metadata=metadata,
            thumbnail_brief=thumbnail_brief,
            opportunity_context=context,
        )

        project_file = project_path / "packaging.json"
        project_file.write_text(json.dumps(artifact.to_dict(), indent=2), encoding="utf-8")

        project.steps.setdefault("packaging", True)
        project.status = "packaging_complete"
        ProjectManager(self.projects_dir)._save_project(project, project_path)
        return artifact

    @staticmethod
    def _category_id_for(category: str) -> str:
        normalized = (category or "Education").strip().casefold()
        mapping = {
            "entertainment": "24",
            "education": "27",
            "science": "28",
            "howto": "26",
            "travel": "19",
            "people": "22",
            "news": "25",
            "music": "10",
            "film": "1",
        }
        return mapping.get(normalized, "27")

    def build_upload_metadata(
        self,
        artifact: PackagingArtifact,
        *,
        category: str = "Entertainment",
        language: str = "en",
        made_for_kids: bool = False,
    ) -> dict[str, Any]:
        if not artifact.selected_title.strip():
            raise ValueError("A selected title is required before building upload metadata.")
        if not artifact.metadata.description.strip():
            raise ValueError("Packaging description is required before building upload metadata.")
        if not artifact.metadata.tags:
            raise ValueError("Packaging tags are required before building upload metadata.")

        return {
            "title": artifact.selected_title.strip(),
            "description": artifact.metadata.description.strip(),
            "tags": list(artifact.metadata.tags),
            "category_id": self._category_id_for(category),
            "category": category,
            "language": (language or "en").strip() or "en",
            "made_for_kids": bool(made_for_kids),
            "thumbnail_notes": artifact.metadata.thumbnail_notes,
            "thumbnail_brief": artifact.thumbnail_brief.to_dict() if artifact.thumbnail_brief else None,
        }

    def build_upload_package(
        self,
        artifact: PackagingArtifact,
        *,
        final_video: str,
        category: str = "Education",
        language: str = "en",
        made_for_kids: bool = False,
        playlist: str | None = None,
        subtitle_file: str = "subtitle_en.vtt",
    ) -> UploadPackage:
        title_variants = artifact.title_options[:3] or [TitleOption(artifact.selected_title, "Selected title")]
        if not title_variants or title_variants[0].title != artifact.selected_title:
            title_variants = [
                *title_variants,
                TitleOption(artifact.selected_title, "Selected title"),
            ]
            title_variants = title_variants[:3]

        default_brief = artifact.thumbnail_brief or ThumbnailBrief(
            subject=artifact.selected_title,
            primary_visual=artifact.selected_title,
            text_layout="Large title text with a single hook image",
            mobile_readability="Keep it readable on mobile.",
            notes="Selected thumbnail brief.",
        )

        thumbnail_variants = [
            ThumbnailVariant(
                variant_name="A",
                prompt=f"Thumbnail A for '{artifact.selected_title}': clean title-first composition with large readable headline and one central object.",
                text=artifact.selected_title,
                notes=(default_brief.notes or "Use a clean, contrast-heavy layout with a single object and large headline."),
            ),
            ThumbnailVariant(
                variant_name="B",
                prompt=f"Thumbnail B for '{artifact.selected_title}': object-first composition with dramatic visual and a tight two-line headline.",
                text=artifact.selected_title[:60],
                notes="Strong object focus, high contrast, best mobile readability.",
            ),
            ThumbnailVariant(
                variant_name="C",
                prompt=f"Thumbnail C for '{artifact.selected_title}': curiosity hook with a single visual symbol and short question framing.",
                text=f"Why {artifact.selected_title.split(':')[0].split(' ')[0]}?",
                notes="Question framing and concise text for quick click-through.",
            ),
        ]

        package = UploadPackage(
            final_video=final_video,
            title_variants=title_variants,
            thumbnail_variants=thumbnail_variants,
            description=artifact.metadata.description.strip(),
            tags=list(artifact.metadata.tags),
            category=category,
            language=(language or "en").strip() or "en",
            audience={"made_for_kids": bool(made_for_kids)},
            altered_synthetic_content={
                "status": "determine_per_video",
                "disclosure": "",
                "never_blindly_mark_true": True,
            },
            chapters={
                "allow_automatic_chapters": True,
                "generate_manual_chapters": True,
                "manual_chapters": [],
            },
            playlist=playlist or "Automatically select the appropriate Ritzz playlist",
            end_screen_plan={
                "enabled": True,
                "placement": "At video end, after final CTA and after 20 seconds of final key image.",
                "recommendations": ["Related topic", "Next video in playlist"],
            },
            cards_plan={
                "enabled": True,
                "recommendations": ["Related curiosity topic", "Previous RITZZ video"],
            },
            visibility={
                "upload_status": "private",
                "scheduling": "MANUAL",
                "embeddable": True,
                "public_statistics": True,
            },
            subtitles={
                "generate_english_subtitles": True,
                "language": "en",
                "file": subtitle_file,
            },
            license="Standard YouTube License",
            ab_test={
                "enabled": True,
                "variant_count": 3,
                "winner_required": True,
                "winner": artifact.selected_title,
            },
        )
        return package

    @staticmethod
    def load_project_packaging(project_path: str | Path) -> PackagingArtifact:
        path = Path(project_path) / "packaging.json"
        if not path.exists():
            raise FileNotFoundError(f"No packaging artifact found at {path}")
        return PackagingArtifact.from_dict(json.loads(path.read_text(encoding="utf-8")))
