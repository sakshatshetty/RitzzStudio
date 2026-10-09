from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from openai import OpenAI
from pydantic import BaseModel, Field

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.project.packaging import (
    PackagingArtifact,
    PackagingMetadata,
    TitleOption,
    YOUTUBE_TAG_CHARACTER_LIMIT,
    youtube_tag_character_count,
)
from modules.qa.engine import record_stage_qa
from modules.qa.models import QAStageResult

METADATA_VERSION = "ritzz-video-metadata-v1"
METADATA_FILENAME = "metadata_packaging.json"
_STOP_WORDS = {
    "about", "after", "again", "also", "among", "because", "before", "being",
    "between", "could", "does", "during", "each", "from", "have", "into",
    "just", "more", "most", "other", "over", "same", "some", "such", "than",
    "that", "their", "them", "then", "there", "these", "they", "this", "those",
    "through", "under", "very", "were", "what", "when", "where", "which",
    "while", "with", "would", "your",
}
_PLACEHOLDER_PATTERN = re.compile(
    r"\b(?:todo|tbd|placeholder|lorem ipsum|insert (?:text|title|description))\b",
    re.IGNORECASE,
)
_TITLE_LEADING_FILLER = {
    "a", "an", "and", "are", "for", "how", "i", "in", "is", "it", "my",
    "of", "on", "or", "the", "that", "this", "to", "what", "why", "with",
    "you", "your",
}


class MetadataTitleOption(BaseModel):
    title: str = Field(min_length=5, max_length=100)
    rationale: str = Field(min_length=1)


class GeneratedVideoMetadata(BaseModel):
    title_options: list[MetadataTitleOption] = Field(min_length=3, max_length=5)
    recommended_title: str = Field(min_length=5, max_length=100)
    title_rationale: str = Field(min_length=1)
    description: str = Field(min_length=50)
    tags: list[str] = Field(min_length=2, max_length=12)


class MetadataGenerator(Protocol):
    def generate(self, context: dict[str, Any]) -> GeneratedVideoMetadata: ...


class OpenAIMetadataGenerator:
    """Generate one structured metadata draft from the finished production context."""

    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    def generate(self, context: dict[str, Any]) -> GeneratedVideoMetadata:
        if self.client is None:
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY is required for metadata packaging.")
            self.client = OpenAI(api_key=OPENAI_API_KEY)
        response = self.client.responses.parse(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Create final YouTube metadata for the actual finished RITZZ video. "
                        "Treat the approved topic, final research, final outline, final script, "
                        "audio-timed storyboard, rendered-video metadata, and QA results as "
                        "the content sources. The final script and storyboard are authoritative. "
                        "Do not invent facts or promise material not present in the video. "
                        "Write 3-5 distinct, concise, accurate title options that create a "
                        "clear curiosity gap about a specific answer in the finished video. "
                        "Consider natural structures such as 'How did...', 'Why did...', "
                        "'What happened to...', and 'How was ... possible?' without forcing "
                        "every title into a template. Avoid generic documentary wording. "
                        "Write for an 8-10 minute general-audience explainer. Recommend one option; "
                        "keep titles within YouTube's 100-character hard limit, front-load the "
                        "specific subject so it survives short-feed truncation, do not choose "
                        "merely for keyword score, and do not copy the topic verbatim. "
                        "Write one complete, natural YouTube description with a clear opening "
                        "hook: the first two lines should clearly say what the video explains "
                        "and what the viewer will learn, followed by the actual examples/concepts covered. "
                        "Do not concatenate fields, repeat the title or hook, copy script passages, "
                        "use placeholders, leave fragments, or end abruptly. Use relevant vidIQ "
                        "keyword evidence only if it accurately describes the finished video. "
                        "Return a compact set of meaningful multi-word search phrases as tags; "
                        "never tokenize the title or description into one-word tags, stuff keywords, "
                        "or add unrelated high-volume phrases. No thumbnail content is requested."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False),
                },
            ],
            text_format=GeneratedVideoMetadata,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no structured video metadata.")
        return parsed


class MetadataPackagingEngine:
    """Create and persist metadata only after a rendered-video QA checkpoint."""

    def __init__(
        self,
        generator: MetadataGenerator | None = None,
        *,
        clock=None,
    ) -> None:
        self.generator = generator or OpenAIMetadataGenerator()
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def package(
        self,
        project_directory: str | Path,
        *,
        production_id: str,
        project_id: str,
        render_metadata: Mapping[str, Any],
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        project_path = Path(project_directory)
        metadata_path = project_path / METADATA_FILENAME
        cached = (
            None
            if force_regenerate
            else self._read_cached(
                metadata_path,
                production_id=production_id,
                project_id=project_id,
            )
        )
        if cached is not None:
            self._sync_legacy_packaging(project_path, cached)
            return cached

        previous = self._read_existing(metadata_path)
        artifact: dict[str, Any] = {
            "metadata_version": METADATA_VERSION,
            "production_id": production_id,
            "project_id": project_id,
            "approved_topic": "",
            "title_options": [],
            "recommended_title": "",
            "selected_title": "",
            "title_rationale": "",
            "description": "",
            "tags": [],
            "vidiq_evidence": {},
            "render_metadata": dict(render_metadata),
            "qa_status": {},
            "status": "PENDING",
            "attempts": int(previous.get("attempts", 0)),
            "created_at": previous.get("created_at") or self.clock(),
            "updated_at": self.clock(),
        }
        artifact.update(
            {
                key: value
                for key, value in previous.items()
                if key in artifact
                and key
                not in {
                    "status",
                    "updated_at",
                    "metadata_version",
                    "production_id",
                    "project_id",
                }
            }
        )
        artifact["updated_at"] = self.clock()
        self._write(metadata_path, artifact)
        artifact["status"] = "RUNNING"
        artifact["attempts"] = int(previous.get("attempts", 0)) + 1
        artifact["updated_at"] = self.clock()
        self._write(metadata_path, artifact)

        try:
            context = self._build_context(
                project_path,
                production_id=production_id,
                project_id=project_id,
                render_metadata=render_metadata,
            )
            artifact["approved_topic"] = context["approved_topic"]
            artifact["vidiq_evidence"] = context["vidiq_evidence"]
            artifact["qa_status"] = context["qa_status"]
            generated = self._generate_with_validation(context, project_path)
            artifact.update(
                {
                    "title_options": [
                        option.model_dump(mode="json")
                        for option in generated.title_options
                    ],
                    "recommended_title": generated.recommended_title.strip(),
                    "selected_title": generated.recommended_title.strip(),
                    "title_rationale": generated.title_rationale.strip(),
                    "description": generated.description.strip(),
                    "tags": [tag.strip() for tag in generated.tags],
                    "title_lint": [
                        self._title_lint(option.title)
                        for option in generated.title_options
                    ],
                    "status": "COMPLETE",
                    "error": None,
                    "updated_at": self.clock(),
                }
            )
            self._write(metadata_path, artifact)
            self._sync_legacy_packaging(project_path, artifact)
            return artifact
        except Exception as exc:
            artifact.update(
                {
                    "status": "FAILED",
                    "error": str(exc),
                    "updated_at": self.clock(),
                }
            )
            self._write(metadata_path, artifact)
            raise

    def _build_context(
        self,
        project_path: Path,
        *,
        production_id: str,
        project_id: str,
        render_metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        selection = self._read_json(project_path / "topic_selection.json", required=True)
        if selection is None:
            raise FileNotFoundError("Approved topic selection is missing.")
        approved_topic = str(selection.get("topic", "")).strip()
        if not approved_topic:
            raise ValueError("Approved topic is missing from topic_selection.json.")

        script = self._read_json(project_path / "script" / "script.json", required=True)
        if script is None:
            raise FileNotFoundError("Completed script is missing.")
        script_text = self._script_text(script)
        if not script_text:
            raise ValueError("The completed script contains no narration.")
        script["full_narration"] = script_text

        video_path = project_path / "video" / "ritzz_test.mp4"
        if not video_path.is_file() or video_path.stat().st_size == 0:
            raise FileNotFoundError(f"Completed rendered video is missing: {video_path}")
        self._validate_render_metadata(render_metadata)

        qa_report = self._read_json(project_path / "qa" / "qa_report.json", required=True)
        if qa_report is None:
            raise FileNotFoundError("Technical QA report is missing.")
        qa_status = self._validate_qa(qa_report)
        package = self._read_json(project_path / "packaging.json", required=False) or {}
        opportunity_context = package.get("opportunity_context", {})
        vidiq_evidence = self._vidiq_evidence(opportunity_context)

        return {
            "production_id": production_id,
            "project_id": project_id,
            "approved_topic": approved_topic,
            "research": self._read_json(project_path / "research" / "research.json"),
            "outline": self._read_json(project_path / "outline" / "outline.json"),
            "final_script": script,
            "final_script_text": script_text,
            "final_storyboard": self._read_json(
                project_path / "storyboard" / "storyboard_audio_timed.json"
            ),
            "render_metadata": dict(render_metadata),
            "qa_status": qa_status,
            "vidiq_evidence": vidiq_evidence,
        }

    def _generate_with_validation(
        self,
        context: dict[str, Any],
        project_directory: Path,
    ) -> GeneratedVideoMetadata:
        failures: list[str] = []
        for _ in range(2):
            try:
                attempt_context = dict(context)
                if failures:
                    attempt_context["qa_feedback"] = (
                        "Correct these validation failures from the previous "
                        "metadata draft:\n" + "\n".join(failures)
                    )
                draft = self.generator.generate(attempt_context)
                if not isinstance(draft, GeneratedVideoMetadata):
                    draft = GeneratedVideoMetadata.model_validate(draft)
                self._validate_draft(draft, context)
                record_stage_qa(
                    project_directory,
                    QAStageResult(
                        stage="metadata_packaging",
                        status="PASS",
                        checks={"metadata_validation": "PASS"},
                    ),
                )
                return draft
            except (ValueError, TypeError) as exc:
                failures.append(str(exc))
                record_stage_qa(
                    project_directory,
                    QAStageResult(
                        stage="metadata_packaging",
                        status="FAIL",
                        checks={"metadata_validation": "FAIL"},
                        findings=[str(exc)],
                        recommendations=[
                            "Correct every listed metadata validation issue."
                        ],
                    ),
                )
        raise ValueError(
            "Generated metadata failed validation twice: " + " | ".join(failures)
        )

    @classmethod
    def _validate_draft(
        cls,
        draft: GeneratedVideoMetadata,
        context: dict[str, Any],
    ) -> None:
        normalized_titles = [
            cls._normalize(option.title) for option in draft.title_options
        ]
        source_words = set(
            cls._words(
                context["approved_topic"] + " " + context["final_script_text"]
            )
        )
        source_numbers = set(
            re.findall(
                r"\b\d+(?:[.,]\d+)?%?\b",
                json.dumps(context, ensure_ascii=False),
            )
        )
        for option in draft.title_options:
            first_words = re.findall(r"[a-z0-9']+", option.title.casefold())[:3]
            if first_words and all(
                word in _TITLE_LEADING_FILLER for word in first_words
            ):
                raise ValueError("Title does not front-load a specific subject.")
            title_words = set(cls._words(option.title))
            if not title_words.intersection(source_words):
                raise ValueError(
                    "Title must name a specific subject from the approved topic or final script."
                )
            if not cls._has_curiosity_signal(option.title):
                raise ValueError(
                    "Title must create a clear curiosity gap about the video's answer."
                )
            if re.search(r"\b\d+(?:[.,]\d+)?%?\b", option.title) and not set(
                re.findall(r"\b\d+(?:[.,]\d+)?%?\b", option.title)
            ).issubset(source_numbers):
                raise ValueError("Title contains a number unsupported by production sources.")
            if re.search(
                r"\b(?:the story of|a documentary about|complete history of|"
                r"ultimate guide to)\b",
                option.title,
                re.IGNORECASE,
            ):
                raise ValueError("Title uses generic documentary wording.")
        if len(set(normalized_titles)) != len(normalized_titles):
            raise ValueError("Title options must be distinct.")
        selected = cls._normalize(draft.recommended_title)
        if selected not in normalized_titles:
            raise ValueError("Recommended title must match one generated title option.")
        if selected == cls._normalize(context["approved_topic"]):
            raise ValueError("A title option must add a specific angle, not copy the topic.")

        description = draft.description.strip()
        if (
            _PLACEHOLDER_PATTERN.search(description)
            or description.endswith(("...", "…"))
            or description[-1:] not in ".?!"
        ):
            raise ValueError("Description contains a placeholder or appears incomplete.")
        if description.count('"') % 2 or description.count("(") != description.count(")"):
            raise ValueError("Description has unclosed punctuation.")
        paragraphs = [
            part.strip()
            for part in re.split(r"\n\s*\n", description)
            if part.strip()
        ]
        if len({cls._normalize(part) for part in paragraphs}) != len(paragraphs):
            raise ValueError("Description contains duplicate paragraphs.")
        if any(
            cls._normalize(paragraph) == cls._normalize(draft.recommended_title)
            for paragraph in paragraphs
        ):
            raise ValueError("Description contains a repeated title block.")
        opening_sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", paragraphs[0])
            if sentence.strip()
        ]
        if len(opening_sentences) < 2:
            raise ValueError(
                "Description opening must clearly explain the video in its first two lines."
            )
        if not set(cls._words(description)).intersection(source_words):
            raise ValueError(
                "Description does not clearly describe the approved topic or final script."
            )
        source_content_words = {
            word
            for word in cls._words(context["final_script_text"])
            if len(word) >= 4
        }
        description_content_words = {
            word
            for word in cls._words(description)
            if len(word) >= 4
        }
        if len(source_content_words.intersection(description_content_words)) < 2:
            raise ValueError(
                "Description does not reflect enough specific content from the final script."
            )
        sentences = [
            cls._normalize(part)
            for part in re.split(r"(?<=[.!?])\s+", description)
            if part.strip()
        ]
        if len(sentences) != len(set(sentences)):
            raise ValueError("Description contains duplicate sentences.")
        if description.casefold().count(draft.recommended_title.casefold()) > 1:
            raise ValueError("Description repeats the selected title.")
        keyword_evidence = context.get("vidiq_evidence", {})
        keyword_phrases = []
        if isinstance(keyword_evidence, dict):
            keyword_phrases.extend(
                str(keyword_evidence.get(key, "")).strip()
                for key in ("primary_keyword",)
            )
            related_keywords = keyword_evidence.get("related_keywords", [])
            if isinstance(related_keywords, list):
                keyword_phrases.extend(
                    str(item).strip()
                    for item in related_keywords
                    if isinstance(item, str)
                )
        if any(
            phrase
            and description.casefold().count(phrase.casefold()) > 3
            for phrase in keyword_phrases
        ):
            raise ValueError("Description repeats a vidIQ keyword excessively.")
        script_sentences = {
            cls._normalize(sentence)
            for sentence in re.split(r"(?<=[.!?])\s+", context["final_script_text"])
            if len(sentence.strip()) >= 45
        }
        if any(sentence in script_sentences for sentence in sentences):
            raise ValueError("Description copies a complete script sentence.")
        description_numbers = set(
            re.findall(r"\b\d+(?:[.,]\d+)?%?\b", description)
        )
        if not description_numbers.issubset(source_numbers):
            raise ValueError("Description contains a number unsupported by production sources.")

        tags = [tag.strip() for tag in draft.tags]
        normalized_tags = [cls._normalize(tag) for tag in tags]
        if len(set(normalized_tags)) != len(normalized_tags):
            raise ValueError("Tags must not contain duplicates.")
        tag_word_sets = [set(cls._words(tag)) for tag in tags]
        for index, current in enumerate(tag_word_sets):
            for previous in tag_word_sets[:index]:
                union = current | previous
                if union and len(current & previous) / len(union) >= 0.8:
                    raise ValueError("Tags must not repeat semantically similar search phrases.")
        title_tokens = set(cls._words(draft.recommended_title))
        evidence_text = " ".join(
            [
                context["approved_topic"],
                json.dumps(context.get("research") or {}, ensure_ascii=False),
                json.dumps(context.get("outline") or {}, ensure_ascii=False),
                context["final_script_text"],
                json.dumps(context.get("final_storyboard") or {}, ensure_ascii=False),
                json.dumps(context.get("vidiq_evidence") or {}, ensure_ascii=False),
            ]
        )
        evidence_words = set(cls._words(evidence_text))
        meaningful_tags: set[str] = set()
        for tag in tags:
            words = cls._words(tag)
            if len(words) < 2:
                raise ValueError(f"Tag must be a meaningful search phrase: {tag}")
            if not set(words).intersection(evidence_words):
                raise ValueError(f"Tag is unrelated to the finished video: {tag}")
            meaningful_tags.update(words)
        if meaningful_tags and meaningful_tags <= title_tokens:
            raise ValueError("Tags appear to be title-tokenized rather than topic phrases.")
        if youtube_tag_character_count(tags) > YOUTUBE_TAG_CHARACTER_LIMIT:
            raise ValueError(
                "Tags exceed YouTube's 500-character limit after accounting "
                "for commas and quotes around multi-word tags."
            )

    @staticmethod
    def _validate_qa(qa_report: dict[str, Any]) -> dict[str, str]:
        stages = qa_report.get("stages", {})
        technical_results = stages.get("technical_qa", [])
        if not technical_results or technical_results[-1].get("status") != "PASS":
            raise ValueError("Technical video QA must pass before metadata packaging.")
        semantic_results = stages.get("rendered_semantic_qa", [])
        semantic_status = (
            semantic_results[-1].get("status", "REVIEW")
            if semantic_results
            else "NOT_RUN"
        )
        if semantic_status == "FAIL":
            raise ValueError("Rendered-video semantic QA failed; metadata packaging is blocked.")
        return {
            "technical_qa": "PASS",
            "rendered_semantic_qa": semantic_status,
        }

    @staticmethod
    def _validate_render_metadata(metadata: Mapping[str, Any]) -> None:
        required = ("width", "height", "fps", "duration_seconds")
        missing = [key for key in required if metadata.get(key) is None]
        if missing:
            raise ValueError(
                "Rendered-video metadata is incomplete: " + ", ".join(missing)
            )

    @staticmethod
    def _vidiq_evidence(context: Any) -> dict[str, Any]:
        if not isinstance(context, dict):
            return {"available": False, "source": "not_persisted"}
        provider = str(context.get("provider", "")).casefold()
        candidate_provider = str(context.get("candidate_provider", "")).casefold()
        has_keywords = bool(
            context.get("primary_keyword")
            or context.get("related_keywords")
            or context.get("related_questions")
            or context.get("current_vidiq_demand_signals")
            or context.get("evidence")
        )
        if "vidiq" not in provider and "vidiq" not in candidate_provider and not has_keywords:
            return {"available": False, "source": "not_persisted"}
        keys = (
            "report_id",
            "candidate_id",
            "provider",
            "primary_keyword",
            "related_keywords",
            "related_questions",
            "evidence",
            "current_vidiq_demand_signals",
            "current_vidiq_demand_available",
            "vidiq_status",
            "competition_saturation_signal",
            "competition_saturation_assessment",
        )
        return {
            "available": True,
            "source": "cached_discovery",
            **{key: context[key] for key in keys if key in context},
        }

    @staticmethod
    def _script_text(script: dict[str, Any]) -> str:
        sections = script.get("sections", [])
        if isinstance(sections, list):
            return "\n\n".join(
                str(section.get("narration", "")).strip()
                for section in sections
                if isinstance(section, dict) and section.get("narration")
            )
        return ""

    @staticmethod
    def _read_json(path: Path, *, required: bool = False) -> dict[str, Any] | None:
        if not path.is_file():
            if required:
                raise FileNotFoundError(f"Required metadata source is missing: {path}")
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Metadata source is unreadable: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise TypeError(f"Metadata source must be a JSON object: {path}")
        return payload

    @classmethod
    def _read_cached(
        cls,
        path: Path,
        *,
        production_id: str,
        project_id: str,
    ) -> dict[str, Any] | None:
        cached = cls._read_json(path)
        if (
            cached
            and cached.get("metadata_version") == METADATA_VERSION
            and cached.get("status") == "COMPLETE"
            and cached.get("production_id") == production_id
            and cached.get("project_id") == project_id
        ):
            GeneratedVideoMetadata.model_validate(
                {
                    "title_options": cached.get("title_options"),
                    "recommended_title": cached.get("selected_title"),
                    "title_rationale": cached.get("title_rationale"),
                    "description": cached.get("description"),
                    "tags": cached.get("tags"),
                }
            )
            if "title_lint" not in cached:
                cached["title_lint"] = [
                    cls._title_lint(item["title"])
                    for item in cached["title_options"]
                ]
                cls._write(path, cached)
            return cached
        return None

    @staticmethod
    def _read_existing(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def _sync_legacy_packaging(
        cls,
        project_path: Path,
        metadata: dict[str, Any],
    ) -> None:
        path = project_path / "packaging.json"
        existing_data = cls._read_json(path) or {}
        existing = PackagingArtifact.from_dict(existing_data)
        existing.selected_title = metadata["selected_title"]
        existing.title_options = [
            TitleOption(
                title=item["title"],
                reason=item.get("rationale", ""),
            )
            for item in metadata["title_options"]
        ]
        existing.metadata = PackagingMetadata(
            category=existing.metadata.category,
            description=metadata["description"],
            tags=list(metadata["tags"]),
            thumbnail_notes=existing.metadata.thumbnail_notes,
        )
        cls._write(path, existing.to_dict())

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))

    @staticmethod
    def _has_curiosity_signal(title: str) -> bool:
        return bool(
            "?" in title
            or re.search(
                r"\b(?:how|why|what|when|where|who|reason|secret|truth|"
                r"possible|behind|works?|creates?|appear|happened|changed)\b",
                title,
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _words(text: str) -> list[str]:
        return [
            word
            for word in re.findall(r"[a-z0-9]+", text.casefold())
            if len(word) > 2 and word not in _STOP_WORDS
        ]

    @staticmethod
    def _title_lint(title: str) -> dict[str, Any]:
        character_count = len(title.strip())
        return {
            "title": title.strip(),
            "characters": character_count,
            "mobile_truncation_risk": character_count > 40,
            "desktop_truncation_risk": character_count > 60,
        }
