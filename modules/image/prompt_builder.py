from modules.storyboard.models import StoryboardScene


class ImagePromptBuilder:
    """
    Builds production image-generation prompts for Ritzz.

    Goals:
    - Simple 2D explainer-animation look
    - One clear visual idea per frame
    - Consistent characters within a video
    - Simple backgrounds
    - Minimal props
    - Optional editorial text
    - Simple handwritten editorial lettering
    - No accidental text when editorial text is absent
    """

    RITZZ_VISUAL_STYLE = (
        "Simple 2D cartoon illustration, "
        "simple stickman-style characters, "
        "thick black outlines, "
        "flat colors, "
        "very minimal shading, "
        "large clear shapes, "
        "simple expressive faces, "
        "clean uncluttered composition, "
        "generous negative space, "
        "minimal visual detail, "
        "easy to understand at a glance, "
        "simple YouTube explainer animation style."
    )

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
        "NO TEXT. "
        "NO TITLES. "
        "NO HEADLINES. "
        "NO LABELS. "
        "NO ARROWS. "
        "NO CAPTIONS. "
        "NO SUBTITLES. "
        "NO SPEECH BUBBLES. "
        "NO INFOGRAPHICS. "
        "NO DIAGRAMS. "
        "NO TIMELINES. "
        "NO ANNOTATIONS. "
        "NO EXPLANATORY WRITING."
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
        "decorative typography, "
        "large headline text, "
        "oversized display typography, "
        "bold display typography, "
        "multicolored text, "
        "yellow text, "
        "bright colored text, "
        "thick text outlines, "
        "3D text, "
        "text effects, "
        "text banners, "
        "burst shapes, "
        "gradient text, "
        "drop shadows, "
        "and any text beyond the requested editorial callout."
    )

    RITZZ_EDITORIAL_TEXT_STYLE = (
        "Render the editorial text as simple, "
        "clean, hand-drawn handwritten lettering. "
        "Use a casual handwritten marker or hand-lettered "
        "appearance rather than a formal computer font. "
        "Keep the lettering medium-large and clearly readable "
        "at 1080p. "
        "Make it visually noticeable but still secondary "
        "to the main illustration. "
        "Use one flat color for the lettering only: plain black "
        "or plain white depending on the background. "
        "This one-color instruction applies only to the editorial letters. "
        "Keep the lettering simple and slightly informal. "
        "Do not use cursive writing that reduces readability. "
        "No decorative lettering, "
        "no thick outline, "
        "no 3D effects, "
        "no gradients, "
        "no bright colors in the lettering, "
        "no shadows, "
        "and no graphic text effects."
    )

    CAMERA_MOTION_MAP = {
        "static": "Static camera.",
        "slow_zoom_in": "Slow gentle zoom in.",
        "slow_zoom_out": "Slow gentle zoom out.",
        "pan_left": "Gentle camera pan left.",
        "pan_right": "Gentle camera pan right.",
        "pan_up": "Gentle camera pan upward.",
        "pan_down": "Gentle camera pan downward.",
    }

    DEFAULT_CHARACTER_PROFILE = ""

    EDITORIAL_ILLUSTRATION_COLOR_INSTRUCTION = (
        "Keep the illustration fully colored using the normal RITZZ flat-color palette. "
        "Use clear colors for the character, clothing, props, and background. "
        "Only the editorial lettering is limited to solid black or white. "
        "Do not make the illustration monochrome, grayscale, black-and-white, or single-color."
    )

    def __init__(
        self,
        base_style: str | None = None,
        character_profile: str | None = None,
    ) -> None:
        self.base_style = (
            base_style.strip()
            if base_style
            else self.RITZZ_VISUAL_STYLE
        )

        self.character_profile = (
            character_profile.strip()
            if character_profile
            else self.DEFAULT_CHARACTER_PROFILE
        )

    def build(
        self,
        scene: StoryboardScene,
    ) -> str:
        """
        Build a production-ready image prompt.
        """

        parts: list[str] = [
            self.base_style,
            "Landscape 16:9 composition.",
        ]

        if self.character_profile:
            parts.append(
                "Character design reference for this video: "
                f"{self.character_profile}"
            )

            parts.append(
                "Keep this character design consistent "
                "throughout this video."
            )

        if scene.visual_description:
            parts.append(
                f"Scene: {scene.visual_description}"
            )

        if scene.character_action:
            parts.append(
                f"Action: {scene.character_action}"
            )

        if scene.background:
            parts.append(
                f"Background: {scene.background}"
            )

        if scene.props:
            parts.append(
                f"Props: {', '.join(scene.props[:3])}"
            )

        has_editorial_text = bool(
            scene.text_overlay.strip()
        )

        if has_editorial_text:
            parts.append(
                self.EDITORIAL_ILLUSTRATION_COLOR_INSTRUCTION
            )

            editorial_text = scene.text_overlay.strip()

            parts.append(
                "Editorial text inside the illustration: "
                f'"{editorial_text}".'
            )

            parts.append(
                self.RITZZ_EDITORIAL_TEXT_STYLE
            )

            parts.append(
                "Keep the editorial text short, "
                "simple, readable, and visually secondary "
                "to the main illustration."
            )

            parts.append(
                "The editorial text is part of the artwork, "
                "not a subtitle or caption."
            )

        parts.append(
            "Keep the scene visually simple. "
            "Use one main visual idea. "
            "Use one main character whenever possible. "
            "Use only the necessary props. "
            "Keep the background simple and secondary. "
            "Do not turn the scene into an infographic."
        )

        camera_description = self.CAMERA_MOTION_MAP.get(
            scene.camera_motion
        )

        if camera_description:
            parts.append(camera_description)

        if has_editorial_text:
            parts.append(
                self.RITZZ_NEGATIVE_STYLE_WITH_EDITORIAL_TEXT
            )
        else:
            parts.append(
                self.RITZZ_STRICT_NO_TEXT
            )

            parts.append(
                self.RITZZ_NEGATIVE_STYLE
            )

        return " ".join(parts)
