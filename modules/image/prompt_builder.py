from typing import ClassVar

from modules.storyboard.models import StoryboardScene
from modules.storyboard.visual_models import VisualWorldBible


class ImagePromptBuilder:
    """
    Builds production image-generation prompts for Ritzz.

    Goals:
    - Simple 2D explainer-animation look
    - One clear visual idea per frame
    - Consistent characters within a video
    - Simple backgrounds
    - Minimal props
    - Historically grounded, unambiguous visual communication
    - No intentional text in video artwork
    """

    RITZZ_HAND_DRAWN_STYLE = (
        "A hand-drawn educational explainer illustration in the established "
        "RITZZ cartoon style. Simple stickman and doodle characters with "
        "expressive faces, bold readable poses, thick black marker-and-ink "
        "outlines, controlled hand-drawn imperfection, clean shapes, flat "
        "colors, and simple shading. Use clear silhouettes and an immediately "
        "understandable foreground action. Draw a contextually appropriate "
        "environment with enough simple, relevant props to explain the scene; "
        "keep details secondary and uncluttered. Use the same clean line-art "
        "treatment, outline weight, and flat-color approach in every frame; "
        "avoid painterly, textured, monochrome, or photorealistic departures. "
        "Playful, informative, "
        "approachable 2D educational-explainer artwork."
    )

    RITZZ_VISUAL_STYLE = RITZZ_HAND_DRAWN_STYLE

    RITZZ_NEGATIVE_STYLE = (
        "Avoid photorealism, cinematic realism, realistic human anatomy, "
        "3D rendering, Pixar-like styling, anime, glossy surfaces, polished "
        "corporate vector art, hyper-detailed digital painting, photographic "
        "textures, excessive shading, crowded compositions, collages, split "
        "panels, visual clutter, unnecessary props, logos, watermarks, "
        "signatures, and all generated text."
    )

    RITZZ_STRICT_NO_TEXT = (
        "NO TEXT. NO TEXT OF ANY KIND, including on physical objects. No words, letters, "
        "captions, labels, callouts, or typography. "
        "numbers, pseudo-writing, logos, watermarks, signatures, or brand marks. "
        "If the narration mentions writing, show the object without reproducing "
        "any writing. DO NOT DRAW EDITORIAL CALLOUT TEXT. NO TITLES. NO HEADLINES. "
        "NO LABELS. NO ARROWS. NO CAPTIONS. NO SUBTITLES. NO SPEECH BUBBLES. "
        "NO INFOGRAPHICS. NO DIAGRAMS. NO TIMELINES. NO ANNOTATIONS. "
        "NO EXPLANATORY WRITING. Do not add words, lettering, captions, labels, "
        "subtitles, callout text, UI text, decorative typography, titles, "
        "headlines, arrows, speech bubbles, infographics, diagrams, timelines, "
        "annotations, watermarks, logos, signatures, or explanatory writing. "
        "Keep the artwork purely visual."
    )

    RITZZ_NEGATIVE_STYLE_WITH_EDITORIAL_TEXT = (
        "Avoid photorealism, "
        "realistic humans, "
        "3D rendering, "
        "detailed textures, "
        "intricate details, "
        "complex scenery, "
        "busy backgrounds, "
        "visual clutter, "
        "excessive shading, "
        "crowds, "
        "unnecessary objects, "
        "digital or geometric display typography, "
        "subtitle styling, "
        "text outline or stroke, "
        "3D text, "
        "text effects, "
        "text banners, "
        "caption bars, "
        "boxes, "
        "background panels, "
        "UI treatment, "
        "and any text beyond the requested editorial callout."
    )

    RITZZ_EDITORIAL_TEXT_STYLE = (
        "Render the exact one-word editorial callout as if a human wrote it "
        "with a thick marker: natural uppercase handwritten letters, slightly "
        "imperfect, bold, and highly readable. Use a flat yellow or white fill "
        "with no outline, stroke, shadow, background, box, banner, caption bar, "
        "or UI treatment. Do not use a digital/block font, geometric display "
        "type, subtitle styling, decorative text effects, or any additional text."
    )

    EDITORIAL_POSITION_MAP: ClassVar[dict[str, str]] = {
        "top_left": "upper-left negative space",
        "top_center": "upper-center negative space",
        "top_right": "upper-right negative space",
        "middle_left": "middle-left negative space",
        "middle_center": "middle-center negative space",
        "middle_right": "middle-right negative space",
        "lower_left": "lower-left negative space",
        "lower_center": "lower-center negative space",
        "lower_right": "lower-right negative space",
    }

    DEFAULT_CHARACTER_PROFILE = (
        "When the recurring RITZZ host appears, keep the same simple stick-figure "
        "identity: a round white head, small black dot eyes, a simple mouth, a "
        "slim black-line body and limbs, consistent head-to-body proportions, "
        "and consistent outline weight. Change only pose and expression. Keep "
        "other people in the same simple 2D cartoon language, and preserve a "
        "person's identity and clothing across scenes when the scene contract "
        "says that person recurs. Clothing and props must match the exact scene "
        "period."
    )

    EDITORIAL_ILLUSTRATION_COLOR_INSTRUCTION = (
        "Keep the illustration fully colored using the normal RITZZ flat-color palette. "
        "Use clear colors for the character, clothing, props, and background."
    )

    def __init__(
        self,
        base_style: str | None = None,
        character_profile: str | None = None,
        visual_world: VisualWorldBible | None = None,
    ) -> None:
        self.base_style = (
            base_style.strip()
            if base_style
            else self.RITZZ_HAND_DRAWN_STYLE
        )

        self.character_profile = (
            character_profile.strip()
            if character_profile is not None
            else self.DEFAULT_CHARACTER_PROFILE
        )
        self.visual_world = visual_world

    def build(
        self,
        scene: StoryboardScene,
        *,
        project_topic: str | None = None,
    ) -> str:
        """Build a production-ready image prompt."""
        parts: list[str] = [
            self.base_style,
            "Landscape 16:9 composition.",
        ]
        if project_topic:
            parts.append(f"FULL PROJECT TOPIC: {project_topic}")
        parts.append(
            "CURRENT SENTENCE — PRIMARY VISUAL INSTRUCTION: "
            f"{scene.sentence or scene.narration}"
        )
        if scene.previous_sentence:
            parts.append(
                "PREVIOUS SENTENCE — continuity context only: "
                f"{scene.previous_sentence}"
            )
        if scene.next_sentence:
            parts.append(
                "NEXT SENTENCE — continuity context only: "
                f"{scene.next_sentence}"
            )
        parts.append(
            "The current sentence determines the image's subject, visible "
            "action, and dominant information. Context must clarify the current "
            "sentence, never replace it or illustrate a neighboring sentence."
        )

        if self.character_profile:
            parts.append(
                "Character design reference for this video: "
                f"{self.character_profile}"
            )
            parts.append(
                "Keep this character design consistent "
                "throughout this video."
            )
            parts.append(
                "Change only the character's pose, expression, or action when "
                "the current sentence requires it; preserve the same recognizable "
                "design, proportions, clothing, colors, and accessories."
            )

        if self.visual_world:
            parts.append(
                "PROJECT VISUAL WORLD: "
                f"{self.visual_world.model_dump_json(exclude={'topic', 'version'})}"
            )
            parts.append(
                "The project bible controls setting, period, and continuity; it "
                "does not override the established RITZZ hand-drawn cartoon style."
            )
            if self.visual_world.historical:
                parts.append(
                    "HISTORICAL / TECHNOLOGY CONSTRAINT: "
                    f"{self.visual_world.technology_ceiling} "
                    "Historical accuracy is mandatory. Do not introduce technology, "
                    "objects, architecture, infrastructure, clothing, tools, "
                    "transportation, or materials belonging to a later period unless "
                    "the scene explicitly depicts a later development."
                )
            if self.visual_world.forbidden_visuals:
                parts.append(
                    "PROJECT FORBIDDEN VISUALS: "
                    + "; ".join(
                        item.description
                        for item in self.visual_world.forbidden_visuals
                    )
                )

        contract = scene.visual_contract
        if contract:
            parts.extend(
                [
                    f"SCENE PURPOSE: {contract.purpose}",
                    f"SCENE SUBJECT: {contract.subject}",
                    f"SCENE ACTION: {contract.action}",
                    f"SCENE ENVIRONMENT: {contract.environment}",
                    f"SCENE HISTORICAL CONTEXT: {contract.historical_context}",
                    "REQUIRED OBJECTS: "
                    + (", ".join(contract.required_objects) or "None specified."),
                    "FORBIDDEN OBJECTS: "
                    + (", ".join(contract.forbidden_objects) or "None specified."),
                    (
                        "AMBIGUITY RESOLUTION: "
                        f"{contract.ambiguity_resolution}"
                    ),
                    "CONTINUITY REQUIREMENTS: "
                    + (
                        "; ".join(contract.continuity_requirements)
                        or "Maintain the project world and recurring identities."
                    ),
                    "ERA LOCK: Depict the period and setting stated in this scene's "
                    "historical context. Do not mix eras or introduce modern objects "
                    "into a historical scene, or historical objects into a present-day "
                    "scene. Change periods only when this contract explicitly marks "
                    "an intentional context transition, and then show only the period "
                    "required for this scene.",
                ]
            )
            if contract.context_transition:
                parts.append(
                    "INTENTIONAL CONTEXT TRANSITION: "
                    f"{contract.context_transition_reason}"
                )

        if scene.visual_description:
            parts.append(f"Scene: {scene.visual_description}")
        if scene.character_action:
            parts.append(f"Action: {scene.character_action}")
        if scene.background:
            parts.append(f"Background: {scene.background}")
        if scene.props:
            parts.append(f"Relevant scene props: {', '.join(scene.props)}")

        parts.append(
            "Show the current sentence as one complete visual idea. "
            "Include enough period- and setting-appropriate environmental "
            "information to explain the situation; keep the foreground action "
            "dominant and the background supportive. Use multiple characters "
            "or objects when the sentence requires them. Maintain the same "
            "RITZZ illustration style and visual world as every other scene. "
            "Use one unified moment and location, not a collage, split-screen, "
            "multi-panel layout, or montage. Do not turn the scene into an infographic."
        )

        parts.append("Static camera; the video uses hard cuts between still images.")
        parts.append(self.RITZZ_STRICT_NO_TEXT)
        parts.append("NEGATIVE CONSTRAINTS: " + self.RITZZ_NEGATIVE_STYLE)

        return " ".join(parts)
