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
        "Hand-drawn educational explainer illustration, "
        "rough marker and pen ink drawing, "
        "annotation-like storyboard frame, "
        "controlled human imperfection, "
        "organic slightly uneven shapes, "
        "subtle natural line-weight variation, "
        "slightly wobbly hand-drawn contours, "
        "Simple 2D cartoon illustration, "
        "simple stickman-style characters, "
        "thick black outlines, confident marker line quality, "
        "flat colors, "
        "very minimal shading, "
        "large clear shapes, "
        "simple expressive faces, "
        "clean uncluttered composition, "
        "generous negative space, "
        "minimal visual detail, "
        "simple illustrated backgrounds with occasional uneven drawn details, "
        "clean and readable rather than messy or unfinished, "
        "easy to understand at a glance, "
        "simple YouTube explainer animation style."
    )

    RITZZ_VISUAL_STYLE = RITZZ_HAND_DRAWN_STYLE

    RITZZ_NEGATIVE_STYLE = (
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
        "unnecessary text."
    )

    RITZZ_STRICT_NO_TEXT = (
        "NO TEXT. DO NOT DRAW EDITORIAL CALLOUT TEXT. NO TITLES. NO HEADLINES. "
        "NO LABELS. NO ARROWS. NO CAPTIONS. NO SUBTITLES. NO SPEECH BUBBLES. "
        "NO INFOGRAPHICS. NO DIAGRAMS. NO TIMELINES. NO ANNOTATIONS. "
        "NO EXPLANATORY WRITING. Do not add editorial words, captions, labels, "
        "subtitles, callout text, UI text, decorative typography, titles, "
        "headlines, arrows, speech bubbles, infographics, diagrams, timelines, "
        "annotations, or explanatory writing. Keep the artwork purely visual."
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

    DEFAULT_CHARACTER_PROFILE = ""

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
            if character_profile
            else self.DEFAULT_CHARACTER_PROFILE
        )
        self.visual_world = visual_world

    def build(
        self,
        scene: StoryboardScene,
    ) -> str:
        """Build a structured, production-ready prompt for one visual scene."""
        parts = [
            f"RITZZ VISUAL STYLE: {self.base_style}",
            "OUTPUT: landscape 16:9 still illustration for an educational explainer.",
        ]
        if self.character_profile:
            parts.append(
                "CHARACTER CONTINUITY: "
                f"{self.character_profile}. Preserve recognizable identity, clothing, "
                "and proportions across scenes while changing action and composition."
            )
        if self.visual_world:
            parts.append(
                "PROJECT VISUAL WORLD: "
                f"{self.visual_world.model_dump_json(exclude={'topic', 'version'})}"
            )
            if self.visual_world.historical:
                parts.append(
                    "HISTORICAL CONTEXT AND TECHNOLOGY CEILING: "
                    f"{self.visual_world.technology_ceiling} Use only period-, "
                    "geography-, and society-appropriate clothing, architecture, "
                    "materials, tools, transport, and technology. Do not introduce "
                    "later-period or modern objects unless the scene explicitly "
                    "depicts a later development."
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
                    f"SCENE SUBJECT (WHO/WHAT): {contract.subject}",
                    f"SCENE ACTION (WHAT HAPPENS): {contract.action}",
                    f"SCENE ENVIRONMENT (WHERE): {contract.environment}",
                    f"SCENE HISTORICAL CONTEXT: {contract.historical_context}",
                    (
                        "SEMANTIC DISAMBIGUATION: "
                        f"{contract.ambiguity_resolution}"
                    ),
                    "REQUIRED OBJECTS: "
                    + (", ".join(contract.required_objects) or "None specified."),
                    "FORBIDDEN OBJECTS: "
                    + (", ".join(contract.forbidden_objects) or "None specified."),
                    "CONTINUITY: "
                    + (
                        "; ".join(contract.continuity_requirements)
                        or "Maintain established recurring identities and project world."
                    ),
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
            parts.append(f"Props: {', '.join(scene.props[:3])}")
        if self.character_profile:
            parts.append(
                "Character design reference for this video: "
                f"{self.character_profile}. Keep this character design consistent "
                "throughout this video."
            )

        parts.extend(
            [
                (
                    "Landscape 16:9 composition. COMPOSITION: Communicate one coherent idea immediately. Use one "
                    "large, clearly silhouetted focal subject; make the main action "
                    "obvious; show enough setting to establish where it happens; avoid "
                    "tiny subjects, competing focal points, and unnecessary empty scenery."
                ),
                (
                    "LIGHTING AND COLOR: Use simple, readable, context-appropriate lighting "
                    "and a small, coherent flat-color palette."
                ),
                (
                    "SIMPLICITY AND READABILITY: Keep the scene visually simple. Use one "
                    "main visual idea. Use one main character whenever possible. Use only "
                    "the necessary props. Keep the background simple and secondary. Use "
                    "expressive poses, clear shapes, and prefer "
                    "visual communication over decorative detail."
                ),
                self.RITZZ_STRICT_NO_TEXT,
                "NEGATIVE CONSTRAINTS: "
                + self.RITZZ_NEGATIVE_STYLE,
                "Static camera; the video uses hard cuts between still images.",
            ]
        )
        return " ".join(parts)
