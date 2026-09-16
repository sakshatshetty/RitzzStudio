from modules.storyboard.models import StoryboardScene


class ImagePromptBuilder:
    """
    Builds standardized image-generation prompts for Ritzz.

    Ritzz has a canonical visual style, but does not have a single
    canonical character. Character appearance can vary between videos
    while remaining consistent within an individual video.
    """

    RITZZ_VISUAL_STYLE = (
        "Simple 2D cartoon illustration, "
        "thick black outlines, flat colors, very minimal shading, "
        "large clear shapes, expressive characters, "
        "minimal visual detail, generous negative space, "
        "clean uncluttered composition, "
        "simple readable visual storytelling, "
        "YouTube explainer animation style."
    )

    RITZZ_NEGATIVE_STYLE = (
        "Avoid photorealism, realistic humans, "
        "3D rendering, detailed textures, intricate details, "
        "busy backgrounds, visual clutter, excessive shading, "
        "watermarks, logos, and unnecessary text."
    )

    RITZZ_NEGATIVE_STYLE_WITH_EDITORIAL_TEXT = (
        "Avoid photorealism, realistic humans, "
        "3D rendering, detailed textures, intricate details, "
        "busy backgrounds, visual clutter, excessive shading, "
        "watermarks, logos, and any text beyond the requested "
        "editorial callout."
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

    def __init__(self, base_style: str | None = None) -> None:
        """
        Initialize the prompt builder.

        Args:
            base_style: Optional custom visual style. If omitted,
                the standard Ritzz visual style is used.
        """
        self.base_style = (
            base_style.strip()
            if base_style
            else self.RITZZ_VISUAL_STYLE
        )

    def build(self, scene: StoryboardScene) -> str:
        """
        Build a complete image-generation prompt for a storyboard scene.
        """

        parts: list[str] = [
            self.base_style,
            "Landscape 16:9 composition.",
        ]

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
                f"Props: {', '.join(scene.props)}"
            )

        if scene.text_overlay.strip():
            parts.append(
                "Editorial text inside the illustration: "
                f'"{scene.text_overlay.strip()}". '
                "Render this as a short, large, bold, readable "
                "visual callout that is naturally integrated into "
                "the composition. It is editorial artwork, not "
                "a subtitle or caption."
            )

        camera_description = self.CAMERA_MOTION_MAP.get(
            scene.camera_motion
        )

        if camera_description:
            parts.append(camera_description)

        if scene.text_overlay.strip():
            parts.append(
                self.RITZZ_NEGATIVE_STYLE_WITH_EDITORIAL_TEXT
            )
        else:
            parts.append(
                self.RITZZ_NEGATIVE_STYLE
            )

        return " ".join(parts)