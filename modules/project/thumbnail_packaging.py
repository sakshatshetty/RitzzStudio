"""Create and validate a dedicated thumbnail after final video metadata."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from openai import OpenAI
from pydantic import BaseModel, Field

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.qa.engine import record_stage_qa
from modules.qa.models import QAStageResult

THUMBNAIL_VERSION = "ritzz-thumbnail-v1"
THUMBNAIL_FILENAME = "thumbnail_packaging.json"
THUMBNAIL_IMAGE_FILENAME = "thumbnail.jpg"
THUMBNAIL_ARTWORK_FILENAME = "thumbnail_artwork.png"
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720
_PLACEHOLDER_PATTERN = re.compile(
    r"\b(?:todo|tbd|placeholder|lorem ipsum|insert (?:text|title))\b",
    re.IGNORECASE,
)
_TEXT_STOP_WORDS = {
    "a", "an", "and", "are", "did", "do", "does", "for", "from", "how",
    "in", "is", "it", "of", "on", "the", "this", "to", "was", "were",
    "what", "when", "where", "which", "who", "why", "with",
}


class ThumbnailConcept(BaseModel):
    concept_id: str
    visual_concept: str = Field(min_length=20)
    main_character_or_object: str = Field(min_length=2)
    situation: str = Field(min_length=8)
    text: str = Field(min_length=1)
    composition: str = Field(min_length=12)
    curiosity_reason: str = Field(min_length=8)
    title_relationship: str = Field(min_length=8)
    artwork_prompt: str = Field(min_length=30)


class ThumbnailConceptDraft(BaseModel):
    concepts: list[ThumbnailConcept] = Field(min_length=3, max_length=5)


class ThumbnailConceptGenerator(Protocol):
    def generate(self, context: dict[str, Any]) -> ThumbnailConceptDraft: ...


class ThumbnailArtworkGenerator(Protocol):
    def generate(self, prompt: str) -> bytes: ...


class ThumbnailImageComposer(Protocol):
    def compose(
        self,
        artwork_path: Path,
        output_path: Path,
        text: str,
    ) -> Path: ...


class OpenAIThumbnailConceptGenerator:
    """Generate several original, accurate concepts without choosing one."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None and not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for thumbnail concepts.")
        self.client = client or OpenAI(api_key=OPENAI_API_KEY)

    def generate(self, context: dict[str, Any]) -> ThumbnailConceptDraft:
        response = self.client.responses.parse(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Create 3-5 distinct thumbnail concepts for the actual RITZZ "
                        "educational video described in the supplied final sources. Do not "
                        "select or rank a winner. Be factually grounded in the approved topic, "
                        "research, final script, final title, and description. Concepts must "
                        "be original compositions, not frames or copies of reference art. "
                        "Use a simple hand-drawn cartoon/doodle style: stickman or doodle "
                        "characters, marker/ink appearance, controlled imperfection, thick "
                        "black outlines, flat bright colors, exaggerated readable poses, one "
                        "dominant idea, minimal clutter, playful educational tone. No "
                        "photorealism, 3D, glossy/anime/vector polish, tiny details, or dark "
                        "complex backgrounds. Each concept must include a short uppercase "
                        "2-4 word text hook (maximum 5 words), complement rather than repeat "
                        "the final title, and describe the exact text separately from artwork. "
                        "The artwork_prompt must request a clean image with absolutely no "
                        "letters, numbers, captions, logos, watermarks, or text; leave clear "
                        "negative space near the lower area for later deterministic text "
                        "compositing. Return 3-5 genuinely distinct concepts."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False),
                },
            ],
            text_format=ThumbnailConceptDraft,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no structured thumbnail concepts.")
        return parsed


class OpenAIThumbnailArtworkGenerator:
    """Generate exactly one clean artwork image for the selected concept."""

    MODEL = "gpt-image-2"

    def __init__(self, client: Any | None = None) -> None:
        if client is None and not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for thumbnail artwork.")
        self.client = client or OpenAI(api_key=OPENAI_API_KEY)

    def generate(self, prompt: str) -> bytes:
        response = self.client.images.generate(
            model=self.MODEL,
            prompt=prompt,
            size="1536x1024",
            quality="medium",
            output_format="png",
            n=1,
        )
        if not response.data or not response.data[0].b64_json:
            raise RuntimeError("OpenAI returned no thumbnail artwork.")
        try:
            image = base64.b64decode(response.data[0].b64_json, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("OpenAI returned invalid thumbnail image data.") from exc
        if not image:
            raise RuntimeError("OpenAI returned empty thumbnail artwork.")
        return image


class FFmpegThumbnailComposer:
    """Crop artwork to 16:9 and render the exact approved hook with FFmpeg."""

    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        font_path: str | Path | None = None,
    ) -> None:
        resolved_ffmpeg = (
            ffmpeg_path
            or os.getenv("RITZZ_FFMPEG_PATH")
            or shutil.which("ffmpeg")
        )
        if not resolved_ffmpeg:
            raise FileNotFoundError(
                "FFmpeg is required to compose the thumbnail text."
            )
        self.ffmpeg_path: str = resolved_ffmpeg
        configured_font = font_path or os.getenv("RITZZ_FONT_PATH")
        font_candidates = (
            Path(configured_font) if configured_font else None,
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
        )
        resolved_font = next(
            (candidate for candidate in font_candidates if candidate and candidate.is_file()),
            None,
        )
        if resolved_font is None:
            raise FileNotFoundError(
                "No supported bold font was found. Set RITZZ_FONT_PATH to a font file."
            )
        self.font_path: Path = resolved_font

    def compose(self, artwork_path: Path, output_path: Path, text: str) -> Path:
        if not artwork_path.is_file() or artwork_path.stat().st_size == 0:
            raise FileNotFoundError(f"Thumbnail artwork is missing: {artwork_path}")
        with tempfile.TemporaryDirectory(prefix="ritzz_thumbnail_") as temp_dir:
            text_file = Path(temp_dir) / "approved-text.txt"
            candidate = Path(temp_dir) / output_path.name
            lines = _wrap_thumbnail_text(text)
            text_file.write_text("\n".join(lines), encoding="utf-8")
            filter_text = (
                "scale=1280:720:force_original_aspect_ratio=increase,"
                "crop=1280:720,"
                "drawtext="
                f"fontfile='{_escape_filter_path(self.font_path)}':"
                f"textfile='{_escape_filter_path(text_file)}':"
                "expansion=none:fontsize=64:fontcolor=yellow:"
                "borderw=6:bordercolor=black:"
                "line_spacing=4:"
                "x=(w-text_w)/2:y=h*0.76-text_h/2"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                [
                    self.ffmpeg_path,
                    "-v", "error",
                    "-y",
                    "-i", str(artwork_path),
                    "-vf", filter_text,
                    "-frames:v", "1",
                    "-q:v", "2",
                    str(candidate),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg thumbnail composition failed: {result.stderr.strip()}"
                )
            if not candidate.is_file() or candidate.stat().st_size == 0:
                raise RuntimeError("FFmpeg did not create the thumbnail image.")
            candidate.replace(output_path)
        return output_path


class ThumbnailPackagingEngine:
    """Persist concepts, render a selected thumbnail, and support safe retries."""

    def __init__(
        self,
        concept_generator: ThumbnailConceptGenerator | None = None,
        artwork_generator: ThumbnailArtworkGenerator | None = None,
        composer: ThumbnailImageComposer | None = None,
        *,
        image_probe: Callable[[Path], Mapping[str, Any]] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.concept_generator = concept_generator
        self.artwork_generator = artwork_generator
        self.composer = composer
        self.image_probe = image_probe or self._probe_image
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def create_concepts(
        self,
        project_directory: str | Path,
        *,
        production_id: str,
        project_id: str,
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        project_path = Path(project_directory)
        artifact_path = project_path / THUMBNAIL_FILENAME
        existing = self._read_artifact(artifact_path)
        if (
            not force_regenerate
            and existing
            and existing.get("production_id") == production_id
            and existing.get("project_id") == project_id
            and existing.get("concepts")
        ):
            return existing

        context = self._build_context(
            project_path,
            production_id=production_id,
            project_id=project_id,
        )
        generator = self.concept_generator or OpenAIThumbnailConceptGenerator()
        validation_error: ValueError | None = None
        for attempt in range(2):
            attempt_context = dict(context)
            if validation_error:
                attempt_context["qa_feedback"] = (
                    "Correct these thumbnail concept validation issues:\n"
                    f"{validation_error}"
                )
            draft = generator.generate(attempt_context)
            try:
                concepts = self._validate_concepts(
                    draft.concepts,
                    selected_title=context["final_title"],
                )
                record_stage_qa(
                    project_path,
                    QAStageResult(
                        stage="thumbnail_concepts",
                        status="PASS",
                        checks={"concept_validation": "PASS"},
                    ),
                )
                break
            except ValueError as exc:
                validation_error = exc
                record_stage_qa(
                    project_path,
                    QAStageResult(
                        stage="thumbnail_concepts",
                        status="FAIL",
                        checks={"concept_validation": "FAIL"},
                        findings=[str(exc)],
                        recommendations=[
                            "Regenerate distinct, accurate thumbnail concepts "
                            + "that satisfy the stated text constraints."
                        ],
                    ),
                )
                if attempt == 1:
                    raise ValueError(
                        "Thumbnail concept QA failed after one automatic "
                        f"correction: {exc}"
                    ) from exc
        else:
            raise RuntimeError(
                "Thumbnail concept QA correction loop ended unexpectedly."
            ) from validation_error
        artifact = {
            "thumbnail_version": THUMBNAIL_VERSION,
            "production_id": production_id,
            "project_id": project_id,
            "status": "AWAITING_CONCEPT_SELECTION",
            "attempts": int(existing.get("attempts", 0)) if existing else 0,
            "created_at": existing.get("created_at", self.clock()) if existing else self.clock(),
            "updated_at": self.clock(),
            "approved_topic": context["approved_topic"],
            "selected_title": context["final_title"],
            "concepts": [concept.model_dump(mode="json") for concept in concepts],
            "selected_concept_id": None,
            "image_path": None,
            "artwork_path": None,
            "qa": {},
            "human_review_status": "PENDING",
            "error": None,
        }
        self._write_artifact(artifact_path, artifact)
        return artifact

    def render_selected(
        self,
        project_directory: str | Path,
        *,
        production_id: str,
        project_id: str,
        concept_id: str,
    ) -> dict[str, Any]:
        project_path = Path(project_directory)
        artifact_path = project_path / THUMBNAIL_FILENAME
        artifact = self._read_artifact(artifact_path)
        if (
            artifact
            and artifact.get("status") == "COMPLETE"
            and artifact.get("production_id") == production_id
            and artifact.get("project_id") == project_id
        ):
            self._validate_existing_thumbnail(project_path, artifact)
            return artifact
        if not artifact or artifact.get("production_id") != production_id:
            raise FileNotFoundError("Thumbnail concepts must be generated before selection.")
        concepts = [
            ThumbnailConcept.model_validate(item)
            for item in artifact.get("concepts", [])
        ]
        concept = next(
            (item for item in concepts if item.concept_id == concept_id),
            None,
        )
        if concept is None:
            raise ValueError(f"Unknown thumbnail concept selection: {concept_id}")
        if project_id != artifact.get("project_id"):
            raise ValueError("Thumbnail concepts belong to a different project.")
        artwork_path = project_path / "video" / THUMBNAIL_ARTWORK_FILENAME
        reuse_artwork = (
            artifact.get("status") in {"FAILED", "RUNNING"}
            and artifact.get("selected_concept_id") == concept_id
            and artwork_path.is_file()
            and artwork_path.stat().st_size > 0
        )

        artifact.update(
            status="RUNNING",
            attempts=int(artifact.get("attempts", 0)) + 1,
            selected_concept_id=concept_id,
            updated_at=self.clock(),
            error=None,
        )
        self._write_artifact(artifact_path, artifact)
        try:
            prompt = self._artwork_prompt(concept)
            composer = self.composer or FFmpegThumbnailComposer()
            if self.composer is None and not shutil.which("ffprobe"):
                raise FileNotFoundError(
                    "FFprobe is required to validate thumbnail readability."
                )
            artwork_path.parent.mkdir(parents=True, exist_ok=True)
            if not reuse_artwork:
                generator = self.artwork_generator or OpenAIThumbnailArtworkGenerator()
                artwork_path.write_bytes(generator.generate(prompt))
            if artwork_path.stat().st_size == 0:
                raise RuntimeError("Thumbnail artwork generator returned an empty image.")
            image_path = project_path / "video" / THUMBNAIL_IMAGE_FILENAME
            image_path = project_path / "video" / THUMBNAIL_IMAGE_FILENAME
            composer.compose(artwork_path, image_path, concept.text)
            qa = self._run_qa(
                image_path,
                artwork_path,
                concept,
                selected_title=str(artifact["selected_title"]),
            )
            artifact.update(
                status="COMPLETE",
                updated_at=self.clock(),
                image_path=str(image_path.relative_to(project_path)),
                artwork_path=str(artwork_path.relative_to(project_path)),
                artwork_prompt=prompt,
                rendered_text=concept.text,
                qa=qa,
                human_review_status="REVIEW",
                error=None,
            )
            self._write_artifact(artifact_path, artifact)
            return artifact
        except Exception as exc:
            artifact.update(
                status="FAILED",
                updated_at=self.clock(),
                error=str(exc),
            )
            self._write_artifact(artifact_path, artifact)
            raise

    def _build_context(
        self,
        project_path: Path,
        *,
        production_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        selection = self._read_json(project_path / "topic_selection.json", required=True)
        topic = str(selection.get("topic", "")).strip()
        if not topic:
            raise ValueError("Approved topic is missing.")
        metadata = self._read_json(project_path / "metadata_packaging.json", required=True)
        if metadata.get("status") != "COMPLETE":
            raise ValueError("Final video metadata must be complete before thumbnail packaging.")
        selected_title = str(metadata.get("selected_title", "")).strip()
        if not selected_title:
            raise ValueError("Final selected title is missing from metadata packaging.")
        script = self._read_json(project_path / "script" / "script.json", required=True)
        research = self._read_json(project_path / "research" / "research.json", required=True)
        video = project_path / "video" / "ritzz_test.mp4"
        if not video.is_file() or video.stat().st_size == 0:
            raise FileNotFoundError(f"Rendered video is missing: {video}")
        return {
            "production_id": production_id,
            "project_id": project_id,
            "approved_topic": topic,
            "final_script": script,
            "final_research": research,
            "final_title": selected_title,
            "final_description": metadata.get("description", ""),
            "rendered_video": {
                "path": str(video),
                "size_bytes": video.stat().st_size,
            },
            "style_specification": (
                "Original simple hand-drawn marker/ink doodle or stickman, thick black "
                "outlines, controlled imperfection, flat bright colors, exaggerated clear "
                "expression or pose, one dominant visual idea, minimal clutter, readable "
                "at small size, playful educational tone. 16:9 composition. No text in art."
            ),
        }

    @classmethod
    def _validate_concepts(
        cls,
        concepts: list[ThumbnailConcept],
        *,
        selected_title: str,
    ) -> list[ThumbnailConcept]:
        if not 3 <= len(concepts) <= 5:
            raise ValueError("Thumbnail ideation must return 3–5 concepts.")
        title_key = cls._normalize(selected_title)
        seen_text: set[str] = set()
        seen_visuals: set[str] = set()
        validated = []
        for index, concept in enumerate(concepts, start=1):
            text = " ".join(concept.text.split()).upper()
            words = text.split()
            normalized_text = cls._normalize(text)
            if not 2 <= len(words) <= 5:
                raise ValueError(
                    f"Thumbnail concept {index} text must contain 2–5 words."
                )
            if len(text) > 24:
                raise ValueError(
                    f"Thumbnail concept {index} text must be at most 24 characters."
                )
            if not text.isupper() or _PLACEHOLDER_PATTERN.search(text):
                raise ValueError(
                    f"Thumbnail concept {index} contains invalid or placeholder text."
                )
            if normalized_text == title_key:
                raise ValueError("Thumbnail text must not repeat the final title.")
            if normalized_text in seen_text:
                raise ValueError("Thumbnail concepts must not use duplicate text.")
            visual_key = cls._normalize(concept.visual_concept)
            if visual_key in seen_visuals:
                raise ValueError("Thumbnail concepts must be visually distinct.")
            normalized_words = normalized_text.split()
            if len(set(normalized_words)) != len(normalized_words):
                raise ValueError("Thumbnail hook contains accidental duplicate words.")
            if all(word.casefold() in _TEXT_STOP_WORDS for word in words):
                raise ValueError("Thumbnail hook must include a meaningful subject word.")
            seen_text.add(normalized_text)
            seen_visuals.add(visual_key)
            validated.append(concept.model_copy(
                update={
                    "concept_id": f"concept-{index}",
                    "text": text,
                }
            ))
        return validated

    @staticmethod
    def _artwork_prompt(concept: ThumbnailConcept) -> str:
        return (
            "Create one dedicated YouTube thumbnail ARTWORK image only, 16:9. "
            "This is an original thumbnail composition, not a video frame. RITZZ style: "
            "simple hand-drawn cartoon/doodle, stickman or doodle character, marker/ink "
            "appearance, controlled imperfection, thick black outlines, flat bright colors, "
            "exaggerated readable pose, one dominant visual concept, minimal clutter, "
            "playful educational tone. Do not use photorealism, cinematic lighting, 3D, "
            "glossy/anime/corporate/vector polish, dark complicated backgrounds, charts, "
            "or multiple unrelated scenes. Use large recognizable forms and strong contrast. "
            "Reserve clean negative space near the lower center for a short editorial hook. "
            "Absolutely no text, letters, words, numbers, captions, labels, symbols, logos, "
            "watermarks, or pseudo-lettering anywhere. The approved text will be composited "
            "separately and must not be rendered into the artwork. Concept: "
            f"{concept.visual_concept} Main subject: {concept.main_character_or_object}. "
            f"Situation: {concept.situation}. Composition: {concept.composition}. "
            f"Additional visual direction: {concept.artwork_prompt}"
        )

    def _run_qa(
        self,
        image_path: Path,
        artwork_path: Path,
        concept: ThumbnailConcept,
        *,
        selected_title: str,
    ) -> dict[str, Any]:
        if not image_path.is_file() or image_path.stat().st_size == 0:
            raise FileNotFoundError("Final thumbnail is missing or empty.")
        if not artwork_path.is_file() or artwork_path.stat().st_size == 0:
            raise FileNotFoundError("Clean thumbnail artwork is missing or empty.")
        probe = self.image_probe(image_path)
        width = probe.get("width")
        height = probe.get("height")
        if width != THUMBNAIL_WIDTH or height != THUMBNAIL_HEIGHT:
            raise ValueError(
                f"Thumbnail must be {THUMBNAIL_WIDTH}x{THUMBNAIL_HEIGHT}; "
                f"received {width}x{height}."
            )
        text = concept.text
        lines = _wrap_thumbnail_text(text)
        maximum_line = max(map(len, lines))
        if maximum_line * 64 * 0.7 > THUMBNAIL_WIDTH - 128:
            raise ValueError("Thumbnail text may exceed the safe horizontal margins.")
        if text != text.upper() or len(text.split()) > 5:
            raise ValueError("Thumbnail text must be uppercase and no longer than five words.")
        if _PLACEHOLDER_PATTERN.search(text):
            raise ValueError("Thumbnail text contains placeholder wording.")
        if self._normalize(text) == self._normalize(selected_title):
            raise ValueError("Thumbnail text must not be identical to the final title.")
        if len(set(self._normalize(text).split())) != len(self._normalize(text).split()):
            raise ValueError("Thumbnail contains duplicate hook text.")
        return {
            "thumbnail_exists": "PASS",
            "image_readable": "PASS",
            "dimensions": "PASS",
            "aspect_ratio": "PASS",
            "exists_and_readable": "PASS",
            "thumbnail_artifact_saved": "PASS",
            "clean_artwork_saved": "PASS",
            "approved_text_present": "PASS",
            "uppercase_text": "PASS",
            "safe_margins": "PASS",
            "text_word_limit": "PASS",
            "duplicate_text": "PASS",
            "placeholder_text": "PASS",
            "title_is_not_thumbnail_text": "PASS",
            "artwork_has_no_editorial_text": "REVIEW",
            "visual_text_review": "REQUIRED",
            "overall_status": "REVIEW",
            "width": width,
            "height": height,
            "aspect_ratio_value": f"{width}:{height}",
            "text_word_count": len(text.split()),
            "maximum_line_characters": maximum_line,
            "text_lines": lines,
            "artwork_has_no_editorial_text_note": (
                "Image-model text cannot be proven absent deterministically; visually "
                "inspect thumbnail_artwork.png during final human review."
            ),
        }

    def _validate_existing_thumbnail(
        self,
        project_path: Path,
        artifact: dict[str, Any],
    ) -> None:
        image_path = project_path / str(artifact.get("image_path", ""))
        if not image_path.is_file() or image_path.stat().st_size == 0:
            raise FileNotFoundError(
                "Completed thumbnail packaging has no reusable thumbnail image."
            )
        artwork_path = project_path / str(artifact.get("artwork_path", ""))
        if not artwork_path.is_file() or artwork_path.stat().st_size == 0:
            raise FileNotFoundError(
                "Completed thumbnail packaging has no reusable clean artwork."
            )
        probe = self.image_probe(image_path)
        if (
            probe.get("width") != THUMBNAIL_WIDTH
            or probe.get("height") != THUMBNAIL_HEIGHT
        ):
            raise ValueError("Completed thumbnail does not have the required 1280x720 size.")

    @staticmethod
    def _probe_image(path: Path) -> Mapping[str, Any]:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise FileNotFoundError(
                "FFprobe is required to validate thumbnail readability."
            )
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"FFprobe could not read the thumbnail: {result.stderr.strip()}"
            )
        streams = json.loads(result.stdout).get("streams", [])
        if not streams:
            raise ValueError("Thumbnail has no readable video/image stream.")
        return streams[0]

    @staticmethod
    def _read_json(path: Path, *, required: bool = False) -> dict[str, Any]:
        if not path.is_file():
            if required:
                raise FileNotFoundError(f"Required thumbnail input is missing: {path}")
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Thumbnail input is unreadable: {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise TypeError(f"Thumbnail input must be a JSON object: {path}")
        return value

    @staticmethod
    def _read_artifact(path: Path) -> dict[str, Any]:
        value = ThumbnailPackagingEngine._read_json(path)
        if value and value.get("thumbnail_version") != THUMBNAIL_VERSION:
            raise ValueError("Saved thumbnail artifact uses an unsupported version.")
        return value

    @staticmethod
    def _write_artifact(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _wrap_thumbnail_text(text: str, width: int = 18) -> list[str]:
    return textwrap.wrap(text.upper(), width=width, break_long_words=False) or [text.upper()]


def _escape_filter_path(path: Path) -> str:
    return (
        path.resolve().as_posix()
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )
