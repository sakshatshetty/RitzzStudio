"""Create and validate a dedicated thumbnail after final video metadata."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from openai import OpenAI
from pydantic import BaseModel, Field

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.qa.engine import record_stage_qa
from modules.qa.models import QAStageResult

THUMBNAIL_VERSION = "ritzz-thumbnail-v2"
THUMBNAIL_FILENAME = "thumbnail_packaging.json"
THUMBNAIL_IMAGE_FILENAME = "thumbnail.jpg"
THUMBNAIL_ARTWORK_FILENAME = "thumbnail_artwork.png"
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720
THUMBNAIL_TEXT_FONT_SIZE = 176
THUMBNAIL_MIN_TEXT_FONT_SIZE = 88
THUMBNAIL_SAFE_MARGIN = 64
THUMBNAIL_MAX_REPAIR_ATTEMPTS = 2
THUMBNAIL_QUALITY_CHECKS = (
    "topic_accuracy",
    "visual_world_accuracy",
    "title_pairing",
    "curiosity_gap",
    "image_text_fit",
    "visual_hook",
    "ritzz_style",
    "focal_clarity",
    "clutter",
    "mobile_composition",
)
_PLACEHOLDER_PATTERN = re.compile(
    r"\b(?:todo|tbd|placeholder|lorem ipsum|insert (?:text|title))\b",
    re.IGNORECASE,
)
_TEXT_STOP_WORDS = {
    "a", "an", "and", "are", "did", "do", "does", "for", "from", "how",
    "in", "is", "it", "of", "on", "the", "this", "to", "was", "were",
    "what", "when", "where", "which", "who", "why", "with",
}
_FONT_WIDTHS = {
    " ": 0.32, "I": 0.32, "J": 0.48, "L": 0.50, "F": 0.56, "T": 0.58,
    "R": 0.66, "P": 0.65, "M": 0.86, "W": 0.92, "B": 0.67, "D": 0.70,
    "O": 0.72, "Q": 0.72, "C": 0.68, "G": 0.73, "S": 0.64, "U": 0.69,
    "V": 0.68, "Y": 0.62, "X": 0.66, "Z": 0.62, "?": 0.58, "!": 0.32,
    "'": 0.28, "-": 0.40, ":": 0.30,
}
_CURIOSITY_ANGLES = (
    "DISCOVERY_REVEAL",
    "PROBLEM_DANGER",
    "UNEXPECTED_MECHANISM",
)
ThumbnailFailureCategory = Literal[
    "TEXT_TOO_SMALL",
    "TEXT_WRAPS",
    "TEXT_CLIPPED",
    "LOW_CONTRAST",
    "WEAK_CURIOSITY",
    "TOO_MUCH_CLUTTER",
    "WRONG_ERA",
    "WEAK_VISUAL_HOOK",
    "TITLE_DUPLICATION",
    "INACCURATE_VISUAL",
    "WRONG_STYLE",
    "OTHER",
]


class ThumbnailConcept(BaseModel):
    concept_id: str
    curiosity_angle: Literal[
        "DISCOVERY_REVEAL",
        "PROBLEM_DANGER",
        "UNEXPECTED_MECHANISM",
    ]
    visual_concept: str = Field(min_length=20)
    main_character_or_object: str = Field(min_length=2)
    situation: str = Field(min_length=8)
    text: str = Field(min_length=1)
    composition: str = Field(min_length=12)
    curiosity_reason: str = Field(min_length=8)
    title_relationship: str = Field(min_length=8)
    artwork_prompt: str = Field(min_length=30)


class ThumbnailConceptDraft(BaseModel):
    concepts: list[ThumbnailConcept] = Field(min_length=3, max_length=3)


class ThumbnailVisualChecks(BaseModel):
    topic_accuracy: Literal["PASS", "REVIEW", "FAIL"]
    visual_world_accuracy: Literal["PASS", "REVIEW", "FAIL"]
    title_pairing: Literal["PASS", "REVIEW", "FAIL"]
    curiosity_gap: Literal["PASS", "REVIEW", "FAIL"]
    image_text_fit: Literal["PASS", "REVIEW", "FAIL"]
    visual_hook: Literal["PASS", "REVIEW", "FAIL"]
    ritzz_style: Literal["PASS", "REVIEW", "FAIL"]
    focal_clarity: Literal["PASS", "REVIEW", "FAIL"]
    clutter: Literal["PASS", "REVIEW", "FAIL"]
    mobile_composition: Literal["PASS", "REVIEW", "FAIL"]


class ThumbnailVisualReview(BaseModel):
    status: Literal["PASS", "REVIEW", "FAIL"]
    checks: ThumbnailVisualChecks
    failure_categories: list[ThumbnailFailureCategory] = Field(default_factory=list)
    rationale: str
    correction_prompt: str = ""


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


class ThumbnailVisualReviewer(Protocol):
    def review(
        self,
        *,
        thumbnail_path: Path,
        artwork_path: Path,
        context: dict[str, Any],
    ) -> ThumbnailVisualReview: ...


class OpenAIThumbnailVisualReviewer:
    """Assess the selected thumbnail artwork and its final text composition."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None and not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for thumbnail visual QA.")
        self.client = client or OpenAI(api_key=OPENAI_API_KEY)

    def review(
        self,
        *,
        thumbnail_path: Path,
        artwork_path: Path,
        context: dict[str, Any],
    ) -> ThumbnailVisualReview:
        images = []
        for path in (thumbnail_path, artwork_path):
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            media_type = "image/jpeg" if path.suffix.casefold() in {".jpg", ".jpeg"} else "image/png"
            images.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{media_type};base64," + encoded,
                    "detail": "low",
                }
            )
        response = self.client.responses.parse(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Review a dedicated RITZZ YouTube thumbnail, not a video frame. "
                        "The first image is the final thumbnail; the second is clean "
                        "artwork before deterministic text composition. Evaluate every "
                        "check against the supplied approved topic, title, research, "
                        "visual-world bible, concept, and exact text. The thumbnail must "
                        "tell one instantly readable curiosity story, use a large focal "
                        "subject, simple hand-drawn marker/ink cartoon style, expressive "
                        "action, and remain readable at small size. The hook should "
                        "complement rather than answer or duplicate the title. Verify "
                        "historical/topic accuracy and reject unsupported era details. "
                        "Check for text clipping, wrapping, legibility, contrast, "
                        "black text boxes, clutter, weak curiosity, and weak visual hooks. "
                        "Return FAIL and a concrete correction for actionable defects; "
                        "use REVIEW only when visual evidence is genuinely uncertain. "
                        "Never request changes to successful unrelated concepts. If a "
                        "FAIL cannot be corrected with a specific concept/artwork change, "
                        "use REVIEW and leave correction_prompt empty."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Exact approved thumbnail text (composited after "
                                "artwork generation):\n"
                                f"{context['concept']['text']}\n\n"
                                "Review context:\n"
                                f"{json.dumps(context, ensure_ascii=False)}"
                            ),
                        },
                        *images,
                    ],
                },
            ],
            text_format=ThumbnailVisualReview,
        )
        parsed = response.output_parsed
        if not isinstance(parsed, ThumbnailVisualReview):
            raise TypeError(
                "Thumbnail visual reviewer returned no valid structured result."
            )
        review_checks = parsed.checks.model_dump()
        missing_checks = set(THUMBNAIL_QUALITY_CHECKS) - set(review_checks)
        if missing_checks:
            raise ValueError(
                "Thumbnail visual review omitted required checks: "
                + ", ".join(sorted(missing_checks))
            )
        failed_checks = {
            name
            for name, status in review_checks.items()
            if status == "FAIL"
        }
        if parsed.status == "PASS" and failed_checks:
            raise ValueError(
                "Thumbnail visual review cannot PASS with failed checks: "
                + ", ".join(sorted(failed_checks))
            )
        if parsed.status == "FAIL" and not failed_checks:
            raise ValueError(
                "Thumbnail visual review must identify at least one failed check."
            )
        if parsed.status == "FAIL" and (
            not parsed.failure_categories or not parsed.correction_prompt.strip()
        ):
            raise ValueError(
                "A failed thumbnail review must include a category and concrete correction."
            )
        return parsed


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
                        "Create exactly three distinct thumbnail concepts for the actual RITZZ "
                        "educational video described in the supplied final sources. Do not "
                        "select or rank a winner. Be factually grounded in the approved topic, "
                        "research, final script, final title, and description. Concepts must "
                        "be original compositions, not frames or copies of reference art. "
                        "Use a simple hand-drawn cartoon/doodle style: stickman or doodle "
                        "characters, marker/ink appearance, controlled imperfection, thick "
                        "black outlines, flat bright colors, exaggerated readable poses, one "
                        "dominant idea, a large focal character or object, minimal "
                        "clutter, playful educational tone. No "
                        "photorealism, 3D, glossy/anime/vector polish, tiny details, or dark "
                        "complex backgrounds. Give the three concepts distinct curiosity "
                        "angles: DISCOVERY_REVEAL, PROBLEM_DANGER, and "
                        "UNEXPECTED_MECHANISM, one each. Each concept must include a short "
                        "uppercase 2-4 word text hook (maximum 5 words), complement rather "
                        "than repeat the final title, and describe the exact text separately "
                        "from artwork. The artwork_prompt must request a clean image with "
                        "absolutely no letters, numbers, captions, logos, watermarks, or text; "
                        "leave a broad, uncluttered horizontal area in the lower quarter for "
                        "large one-line deterministic text composition. Return exactly three "
                        "genuinely different concepts."
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
        configured_font = (
            font_path
            or os.getenv("RITZZ_THUMBNAIL_FONT_PATH")
            or os.getenv("RITZZ_FONT_PATH")
        )
        font_candidates = (
            Path(configured_font) if configured_font else None,
            Path("/usr/share/fonts/truetype/comic-neue/ComicNeue-Bold.ttf"),
            Path("/usr/share/fonts/truetype/comic-neue/ComicNeue-Bold.otf"),
            Path("C:/Windows/Fonts/comicbd.ttf"),
            Path("C:/Windows/Fonts/comic.ttf"),
            Path("/System/Library/Fonts/Supplemental/Chalkboard.ttc"),
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
        self.last_text_color: str | None = None
        self.last_layout: dict[str, Any] | None = None

    def compose(self, artwork_path: Path, output_path: Path, text: str) -> Path:
        if not artwork_path.is_file() or artwork_path.stat().st_size == 0:
            raise FileNotFoundError(f"Thumbnail artwork is missing: {artwork_path}")
        normalized_text = " ".join(text.split()).upper()
        if "\n" in text or not normalized_text:
            raise ValueError("Thumbnail hook must be non-empty and rendered on one line.")
        layout = _thumbnail_text_layout(normalized_text)
        color = self._text_color_for_background(artwork_path)
        self.last_layout = layout
        self.last_text_color = color
        with tempfile.TemporaryDirectory(prefix="ritzz_thumbnail_") as temp_dir:
            text_file = Path(temp_dir) / "approved-text.txt"
            candidate = Path(temp_dir) / output_path.name
            text_file.write_text(normalized_text, encoding="utf-8")
            filter_text = (
                "scale=1280:720:force_original_aspect_ratio=increase,"
                "crop=1280:720,"
                "drawtext="
                f"fontfile='{_escape_filter_path(self.font_path)}':"
                f"textfile='{_escape_filter_path(text_file)}':"
                f"expansion=none:fontsize={layout['font_size']}:fontcolor={color}:"
                "borderw=4:bordercolor=black:"
                "shadowx=4:shadowy=5:shadowcolor=black@0.85:"
                "x=(w-text_w)/2:y=h*0.75-text_h/2"
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

    def _text_color_for_background(self, artwork_path: Path) -> str:
        filter_graph = (
            "scale=1280:720:force_original_aspect_ratio=increase,"
            "crop=1280:720,crop=960:180:160:450,"
            "scale=1:1:flags=area,format=rgb24"
        )
        result = subprocess.run(
            [
                self.ffmpeg_path,
                "-v", "error",
                "-i", str(artwork_path),
                "-vf", filter_graph,
                "-frames:v", "1",
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or len(result.stdout) < 3:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                "Could not sample the thumbnail text background for contrast: "
                + (error or "FFmpeg returned no RGB sample.")
            )
        red, green, blue = result.stdout[:3]
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        return "white" if luminance >= 160 else "yellow"


class ThumbnailPackagingEngine:
    """Persist concepts, render a selected thumbnail, and support safe retries."""

    def __init__(
        self,
        concept_generator: ThumbnailConceptGenerator | None = None,
        artwork_generator: ThumbnailArtworkGenerator | None = None,
        composer: ThumbnailImageComposer | None = None,
        *,
        visual_reviewer: ThumbnailVisualReviewer | None = None,
        image_probe: Callable[[Path], Mapping[str, Any]] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.concept_generator = concept_generator
        self.artwork_generator = artwork_generator
        self.composer = composer
        self.visual_reviewer = visual_reviewer
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
        context = self._build_context(
            project_path,
            production_id=production_id,
            project_id=project_id,
        )
        input_fingerprint = self._context_fingerprint(context)
        if (
            not force_regenerate
            and existing
            and existing.get("thumbnail_version") == THUMBNAIL_VERSION
            and existing.get("production_id") == production_id
            and existing.get("project_id") == project_id
            and existing.get("concepts")
            and existing.get("input_fingerprint") == input_fingerprint
        ):
            return existing

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
            "input_fingerprint": input_fingerprint,
            "concepts": [concept.model_dump(mode="json") for concept in concepts],
            "selected_concept_id": None,
            "image_path": None,
            "artwork_path": None,
            "qa": {},
            "retry_history": [],
            "visual_world_bible": context.get("visual_world_bible"),
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
            if artifact.get("selected_concept_id") != concept_id:
                raise ValueError(
                    "A completed thumbnail uses a different concept; select the "
                    "saved concept or explicitly regenerate thumbnail concepts."
                )
            self._validate_existing_thumbnail(project_path, artifact)
            return artifact
        if (
            not artifact
            or artifact.get("production_id") != production_id
            or artifact.get("thumbnail_version") != THUMBNAIL_VERSION
        ):
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
        image_path = project_path / "video" / THUMBNAIL_IMAGE_FILENAME
        context = self._build_context(
            project_path,
            production_id=production_id,
            project_id=project_id,
        )
        retry_history = artifact.get("retry_history", [])
        if not isinstance(retry_history, list) or any(
            not isinstance(item, dict) for item in retry_history
        ):
            raise ValueError("Thumbnail retry history must be a list.")
        reuse_artwork = (
            artifact.get("status") in {"FAILED", "RUNNING"}
            and artifact.get("selected_concept_id") == concept_id
            and artwork_path.is_file()
            and artwork_path.stat().st_size > 0
            and (
                not retry_history
                or retry_history[-1].get("status") not in {"FAIL", "REVIEW"}
            )
        )

        artifact.update(
            status="RUNNING",
            selected_concept_id=concept_id,
            updated_at=self.clock(),
            error=None,
        )
        self._write_artifact(artifact_path, artifact)
        try:
            composer = self.composer or FFmpegThumbnailComposer()
            if self.composer is None and not shutil.which("ffprobe"):
                raise FileNotFoundError(
                    "FFprobe is required to validate thumbnail readability."
                )
            artwork_path.parent.mkdir(parents=True, exist_ok=True)
            generator = self.artwork_generator or OpenAIThumbnailArtworkGenerator()
            reviewer = self.visual_reviewer or OpenAIThumbnailVisualReviewer()
            correction = ""
            for repair_index in range(THUMBNAIL_MAX_REPAIR_ATTEMPTS + 1):
                prompt = self._artwork_prompt(
                    concept,
                    visual_world=context.get("visual_world_bible"),
                    correction=correction,
                )
                artifact["attempts"] = int(artifact.get("attempts", 0)) + 1
                artifact["updated_at"] = self.clock()
                self._write_artifact(artifact_path, artifact)
                if not reuse_artwork or repair_index > 0:
                    artwork_path.write_bytes(generator.generate(prompt))
                if not artwork_path.is_file() or artwork_path.stat().st_size == 0:
                    raise RuntimeError("Thumbnail artwork generator returned an empty image.")
                reuse_artwork = False
                composer.compose(artwork_path, image_path, concept.text)
                qa = self._run_qa(
                    image_path,
                    artwork_path,
                    concept,
                    selected_title=str(artifact["selected_title"]),
                    text_color=getattr(composer, "last_text_color", None),
                )
                review_context = {
                    key: context.get(key)
                    for key in (
                        "approved_topic",
                        "final_title",
                        "final_description",
                        "final_research",
                        "visual_world_bible",
                    )
                }
                review_context["concept"] = concept.model_dump(mode="json")
                review_context["deterministic_layout"] = {
                    key: qa[key]
                    for key in (
                        "text_word_count",
                        "text_line_count",
                        "font_size",
                        "mobile_font_size",
                        "text_width_ratio",
                        "text_color",
                    )
                }
                review = reviewer.review(
                    thumbnail_path=image_path,
                    artwork_path=artwork_path,
                    context=review_context,
                )
                qa["visual_review"] = review.model_dump(mode="json")
                qa["automated_status"] = review.status
                qa["overall_status"] = "REVIEW"
                attempt_record = {
                    "attempt": int(artifact["attempts"]),
                    "concept_id": concept_id,
                    "status": review.status,
                    "failure_categories": review.failure_categories,
                    "rationale": review.rationale,
                    "correction_prompt": review.correction_prompt or None,
                    "artwork_prompt_sha256": hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest(),
                }
                retry_history.append(attempt_record)
                artifact["retry_history"] = retry_history
                record_stage_qa(
                    project_path,
                    QAStageResult(
                        stage="thumbnail_visual_qa",
                        status=review.status,
                        checks=review.checks.model_dump(),
                        findings=[review.rationale] if review.rationale else [],
                        recommendations=(
                            [review.correction_prompt]
                            if review.correction_prompt
                            else []
                        ),
                        reviewer="openai_vision",
                    ),
                )
                if review.status in {"FAIL", "REVIEW"} and review.correction_prompt.strip():
                    attempt_record["repair_applied"] = (
                        repair_index < THUMBNAIL_MAX_REPAIR_ATTEMPTS
                    )
                    self._write_artifact(artifact_path, artifact)
                    if repair_index < THUMBNAIL_MAX_REPAIR_ATTEMPTS:
                        correction = review.correction_prompt.strip()
                        continue
                    raise ValueError(
                        "Thumbnail visual QA still fails after two concept-only "
                        "repairs; inspect thumbnail_packaging.json retry_history."
                    )
                if review.status == "FAIL":
                    raise ValueError(
                        "Thumbnail visual QA failed without an actionable correction."
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
                    retry_history=retry_history,
                    error=None,
                )
                self._write_artifact(artifact_path, artifact)
                return artifact
            raise RuntimeError("Thumbnail repair loop ended unexpectedly.")
        except Exception as exc:
            artifact.update(
                status="FAILED",
                updated_at=self.clock(),
                error=str(exc),
                retry_history=retry_history,
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
        from modules.storyboard.visual_context import load_visual_world_bible

        visual_world = load_visual_world_bible(project_path)
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
            "visual_world_bible": (
                visual_world.model_dump(mode="json")
                if visual_world is not None
                else None
            ),
            "style_specification": (
                "Original RITZZ hand-drawn cartoon/stickman, marker and ink illustration, "
                "controlled imperfection, thick dark outlines, bright flat colors, "
                "exaggerated readable action, one dominant visual idea, large foreground "
                "subject, simple context-rich background, mobile-first 16:9 composition. "
                "Thumbnail text is composited separately and must not appear in artwork."
            ),
            "rendered_video": {
                "path": str(video),
                "size_bytes": video.stat().st_size,
            },
        }

    @classmethod
    def _validate_concepts(
        cls,
        concepts: list[ThumbnailConcept],
        *,
        selected_title: str,
    ) -> list[ThumbnailConcept]:
        if len(concepts) != 3:
            raise ValueError("Thumbnail ideation must return exactly 3 concepts.")
        title_key = cls._normalize(selected_title)
        title_tokens = {
            token
            for token in title_key.split()
            if token not in _TEXT_STOP_WORDS
        }
        seen_text: set[str] = set()
        seen_visuals: set[str] = set()
        visual_signatures: list[set[str]] = []
        seen_angles: set[str] = set()
        validated = []
        for index, concept in enumerate(concepts, start=1):
            text = " ".join(concept.text.split()).upper()
            words = text.split()
            normalized_text = cls._normalize(text)
            if not 2 <= len(words) <= 5:
                raise ValueError(
                    f"Thumbnail concept {index} text must contain 2–5 words."
                )
            if not text.isupper() or _PLACEHOLDER_PATTERN.search(text):
                raise ValueError(
                    f"Thumbnail concept {index} contains invalid or placeholder text."
                )
            hook_tokens = {
                token
                for token in normalized_text.split()
                if token not in _TEXT_STOP_WORDS
            }
            if normalized_text == title_key or (
                len(hook_tokens) >= 2
                and len(hook_tokens & title_tokens) / len(hook_tokens) >= 0.7
            ):
                raise ValueError(
                    "Thumbnail text must not repeat the final title's central wording."
                )
            layout = _thumbnail_text_layout(text)
            if layout["mobile_font_size"] < THUMBNAIL_MIN_TEXT_FONT_SIZE * 320 / THUMBNAIL_WIDTH:
                raise ValueError(
                    f"Thumbnail concept {index} text is too small for mobile."
                )
            if layout["width_ratio"] < 0.30:
                raise ValueError(
                    f"Thumbnail concept {index} hook is too short to dominate the composition."
                )
            if normalized_text in seen_text:
                raise ValueError("Thumbnail concepts must not use duplicate text.")
            if concept.curiosity_angle in seen_angles:
                raise ValueError("Each thumbnail must use a different curiosity angle.")
            visual_key = cls._normalize(concept.visual_concept)
            if visual_key in seen_visuals:
                raise ValueError("Thumbnail concepts must be visually distinct.")
            if re.search(
                r"\b(tiny|miniature|distant|small)\b",
                concept.main_character_or_object.casefold(),
            ):
                raise ValueError(
                    f"Thumbnail concept {index} uses a tiny or distant focal subject."
                )
            signature_text = (
                f"{concept.visual_concept} {concept.main_character_or_object} "
                f"{concept.situation} {concept.composition}"
            )
            signature = {
                token
                for token in cls._normalize(signature_text).split()
                if token not in _TEXT_STOP_WORDS and len(token) > 2
            }
            for previous_signature in visual_signatures:
                union = signature | previous_signature
                similarity = (
                    len(signature & previous_signature) / len(union)
                    if union
                    else 1.0
                )
                if similarity >= 0.72:
                    raise ValueError(
                        "Thumbnail concepts must differ in focal object, action, "
                        "composition, and visual interpretation."
                    )
            normalized_words = normalized_text.split()
            if len(set(normalized_words)) != len(normalized_words):
                raise ValueError("Thumbnail hook contains accidental duplicate words.")
            if all(word.casefold() in _TEXT_STOP_WORDS for word in words):
                raise ValueError("Thumbnail hook must include a meaningful subject word.")
            seen_text.add(normalized_text)
            seen_visuals.add(visual_key)
            seen_angles.add(concept.curiosity_angle)
            visual_signatures.append(signature)
            validated.append(concept.model_copy(
                update={
                    "concept_id": f"concept-{index}",
                    "text": text,
                }
            ))
        if seen_angles != set(_CURIOSITY_ANGLES):
            raise ValueError(
                "The three concepts must cover discovery/reveal, problem/danger, "
                "and unexpected mechanism angles."
            )
        return validated

    @staticmethod
    def _artwork_prompt(
        concept: ThumbnailConcept,
        *,
        visual_world: dict[str, Any] | None = None,
        correction: str = "",
    ) -> str:
        world_instruction = (
            "Project visual-world constraints: "
            + json.dumps(visual_world, ensure_ascii=False)
            + ". "
            if visual_world
            else ""
        )
        correction_instruction = (
            f"Targeted thumbnail QA repair: {correction}. "
            "Change only this selected concept's artwork while preserving the "
            "approved topic and text. "
            if correction
            else ""
        )
        return (
            "Create one dedicated YouTube thumbnail ARTWORK image only, 16:9. "
            "This is an original thumbnail composition, not a video frame. RITZZ style: "
            "simple hand-drawn cartoon/doodle, stickman or doodle character, marker/ink "
            "appearance, controlled imperfection, thick black outlines, flat bright colors, "
            "exaggerated readable pose, one dominant visual concept, minimal clutter, "
            "playful educational tone. Do not use photorealism, cinematic lighting, 3D, "
            "glossy/anime/corporate/vector polish, dark complicated backgrounds, charts, "
            "or multiple unrelated scenes. Use large recognizable foreground forms and "
            "strong color/value separation. Use almost the full canvas effectively. "
            "Keep the main subject, face, and key object large and away from extreme edges. "
            "Show one expressive action and one clear curiosity hook. Reserve a broad, "
            "uncluttered horizontal space across the lower quarter for large one-line text "
            "to be composited later; do not draw a box or banner there. "
            "Absolutely no text, letters, words, numbers, captions, labels, symbols, logos, "
            "watermarks, or pseudo-lettering anywhere. The approved text will be composited "
            "separately and must not be rendered into the artwork. Concept: "
            f"{world_instruction}{correction_instruction}"
            f"Curiosity angle: {concept.curiosity_angle}. "
            f"{concept.visual_concept} Main subject: {concept.main_character_or_object}. "
            f"Situation: {concept.situation}. Composition: {concept.composition}. "
            f"Additional visual direction: {concept.artwork_prompt}"
        )

    @staticmethod
    def _context_fingerprint(context: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _run_qa(
        self,
        image_path: Path,
        artwork_path: Path,
        concept: ThumbnailConcept,
        *,
        selected_title: str,
        text_color: str | None = None,
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
        text = " ".join(concept.text.split()).upper()
        layout = _thumbnail_text_layout(text)
        title_tokens = {
            token
            for token in self._normalize(selected_title).split()
            if token not in _TEXT_STOP_WORDS
        }
        hook_tokens = {
            token
            for token in self._normalize(text).split()
            if token not in _TEXT_STOP_WORDS
        }
        title_overlap = (
            len(title_tokens & hook_tokens) / len(hook_tokens)
            if hook_tokens
            else 1.0
        )
        if _PLACEHOLDER_PATTERN.search(text):
            raise ValueError("Thumbnail text contains placeholder wording.")
        if title_overlap >= 0.7:
            raise ValueError(
                "Thumbnail text repeats the final title's central wording."
            )
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
            "safe_margins": "PASS" if layout["estimated_text_width"] <= width - 2 * THUMBNAIL_SAFE_MARGIN else "FAIL",
            "line_count": "PASS",
            "one_line_preference": "PASS",
            "text_size": "PASS" if layout["font_size"] >= THUMBNAIL_MIN_TEXT_FONT_SIZE else "FAIL",
            "mobile_readability": "PASS" if layout["mobile_font_size"] >= 22 else "FAIL",
            "no_black_text_box": "PASS",
            "text_word_limit": "PASS",
            "duplicate_text": "PASS",
            "placeholder_text": "PASS",
            "title_is_not_thumbnail_text": "PASS",
            "title_nonduplication": "PASS",
            "artwork_has_no_editorial_text": "REVIEW",
            "visual_text_review": "REQUIRED",
            "overall_status": "REVIEW",
            "width": width,
            "height": height,
            "aspect_ratio_value": f"{width}:{height}",
            "text_word_count": len(text.split()),
            "text_line_count": layout["line_count"],
            "maximum_line_characters": max(map(len, layout["lines"])),
            "text_lines": layout["lines"],
            "font_size": layout["font_size"],
            "mobile_font_size": layout["mobile_font_size"],
            "estimated_text_width": layout["estimated_text_width"],
            "text_width_ratio": round(layout["width_ratio"], 3),
            "text_color": text_color or "selected by background contrast sampler",
            "title_hook_token_overlap": round(title_overlap, 3),
            "artwork_has_no_editorial_text_note": (
                "The clean artwork is independently checked by visual QA; human review "
                "remains required for final selection."
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
        if value and value.get("thumbnail_version") not in {
            "ritzz-thumbnail-v1",
            THUMBNAIL_VERSION,
        }:
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


def _thumbnail_text_layout(
    text: str,
    *,
    width: int = THUMBNAIL_WIDTH,
) -> dict[str, Any]:
    normalized = " ".join(text.split()).upper()
    if not normalized:
        raise ValueError("Thumbnail text must not be empty.")
    width_units = sum(_FONT_WIDTHS.get(character, 0.66) for character in normalized)
    maximum_width = width - 2 * THUMBNAIL_SAFE_MARGIN
    font_size = min(
        THUMBNAIL_TEXT_FONT_SIZE,
        int((width * 0.55) / width_units),
    )
    if font_size < THUMBNAIL_MIN_TEXT_FONT_SIZE:
        raise ValueError(
            "Thumbnail hook cannot fit on one readable line; regenerate a shorter hook "
            "or recompose the concept."
        )
    estimated_width = round(width_units * font_size)
    if estimated_width > maximum_width:
        raise ValueError(
            "Thumbnail hook would clip outside the safe composition area."
        )
    return {
        "lines": [normalized],
        "line_count": 1,
        "font_size": font_size,
        "mobile_font_size": round(font_size * 320 / width),
        "estimated_text_width": estimated_width,
        "width_ratio": estimated_width / width,
    }


def _escape_filter_path(path: Path) -> str:
    return (
        path.resolve().as_posix()
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )
