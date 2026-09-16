from modules.storyboard.models import StoryboardScene


class ImagePromptBuilder:
    """
    Builds consistent image-generation prompts for Ritzz.

    The builder combines the storyboard scene information with
    the channel's standard visual style.
    """

    DEFAULT_STYLE = (
        "Simple 2D stickman cartoon illustration, "
        "thick black outlines, flat colors, minimal shading, "
        "clean composition, simple shapes, "
        "expressive characters, uncluttered background."
    )

    NEGATIVE_STYLE = (
        "Avoid photorealism, realistic humans, "
        "3D rendering, detailed textures, complex backgrounds, "
        "watermarks, logos, and unnecessary text."
    )

    def __init__(
        self,
        base_style: str | None = None,
    ) -> None:
        self.base_style = (
            base_style.strip()
            if base_style
            else self.DEFAULT_STYLE
        )

    def build(
        self,
        scene: StoryboardScene,
    ) -> str:
        """
        Build a complete image-generation prompt
        from a storyboard scene.
        """

        parts: list[str] = []

        parts.append(self.base_style)

        if scene.visual_description.strip():
            parts.append(
                f"Scene: {scene.visual_description.strip()}"
            )

        if scene.character_action.strip():
            parts.append(
                f"Action: {scene.character_action.strip()}"
            )

        if scene.background.strip():
            parts.append(
                f"Background: {scene.background.strip()}"
            )

        if scene.props:
            props = ", ".join(
                prop.strip()
                for prop in scene.props
                if prop.strip()
            )

            if props:
                parts.append(
                    f"Props: {props}."
                )

        if scene.text_overlay.strip():
            parts.append(
                f"Text overlay: {scene.text_overlay.strip()}."
            )

        parts.append(
            f"Camera: {self._camera_description(scene)}"
        )

        parts.append(self.NEGATIVE_STYLE)

        return " ".join(parts)

    @staticmethod
    def _camera_description(
        scene: StoryboardScene,
    ) -> str:
        descriptions = {
            "static": "static composition",
            "slow_zoom_in": "subtle zoom-in composition",
            "slow_zoom_out": "subtle zoom-out composition",
            "pan_left": "composition suitable for a slow pan left",
            "pan_right": "composition suitable for a slow pan right",
            "pan_up": "composition suitable for a slow pan upward",
            "pan_down": "composition suitable for a slow pan downward",
        }

        return descriptions.get(
            scene.camera_motion,
            "static composition",
        )