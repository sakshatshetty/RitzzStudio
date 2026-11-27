"""Create deterministic edit directions for Pro-mode video renders."""

from __future__ import annotations

import json
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from modules.storyboard.models import CalloutPosition, Storyboard
from modules.video.image_asset_qa import detect_visible_text
from modules.video.models import VideoAssemblyPlan

Transition = Literal["cut", "fade"]
SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".m4a", ".ogg", ".wav"}
MAX_SOUND_EFFECT_ARCHIVE_BYTES = 250 * 1024 * 1024
MAX_SOUND_EFFECT_UNPACKED_BYTES = 500 * 1024 * 1024
MAX_SOUND_EFFECT_ARCHIVE_FILES = 256


class SoundEffectDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    tags: list[str] = Field(min_length=1)


class ProSoundEffectEvent(BaseModel):
    file_path: str
    start_seconds: float = Field(ge=0)
    volume: float = Field(default=0.16, ge=0, le=0.5)
    cue: str


class ProSceneDirection(BaseModel):
    scene_id: str
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    incoming_transition: Transition = "cut"
    transition_duration_seconds: float = Field(default=0, ge=0, le=0.5)
    overlay_text: str = ""
    overlay_position: CalloutPosition = "top_center"


class ProEditPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    total_duration_seconds: float = Field(gt=0)
    scenes: list[ProSceneDirection] = Field(min_length=1)
    sound_effects: list[ProSoundEffectEvent] = Field(default_factory=list)


class ProEditingDirector:
    """Derive restrained transitions, existing editorial overlays, and SFX cues."""

    TRANSITION_DURATION_SECONDS = 0.3
    SOUND_EFFECT_VOLUME = 0.16
    CUE_KEYWORDS: ClassVar[dict[str, tuple[str, ...]]] = {
        "reveal": ("reveal", "reveals", "secret", "surprise", "turns out"),
        "impact": ("impact", "crash", "strike", "smash", "explosion"),
        "click": ("click", "tap", "press", "switch"),
        "water": ("ocean", "sea", "wave", "river", "water"),
    }

    def create_plan(
        self,
        storyboard: Storyboard,
        assembly_plan: VideoAssemblyPlan,
        sound_effects_directory: str | Path,
    ) -> ProEditPlan:
        if storyboard.topic != assembly_plan.topic:
            raise ValueError("Storyboard topic does not match the Pro edit timeline.")
        if len(storyboard.scenes) != len(assembly_plan.clips):
            raise ValueError("Storyboard and Pro edit timeline have different scene counts.")

        effects = self._load_sound_effects(sound_effects_directory)
        directions: list[ProSceneDirection] = []
        sound_events: list[ProSoundEffectEvent] = []

        for index, (scene, clip) in enumerate(
            zip(storyboard.scenes, assembly_plan.clips, strict=True)
        ):
            if scene.scene_id != clip.scene_id:
                raise ValueError("Storyboard and Pro edit timeline scene order differs.")

            section_changed = (
                index > 0
                and scene.section_id != storyboard.scenes[index - 1].section_id
            )
            use_fade = index > 0 and (
                section_changed or scene.transition == "fade"
            )
            transition: Transition = "fade" if use_fade else "cut"
            transition_duration = (
                self.TRANSITION_DURATION_SECONDS if use_fade else 0
            )

            overlay_text = " ".join(scene.text_overlay.split())
            if any(character in scene.text_overlay for character in "\r\n"):
                raise ValueError(
                    f"{scene.scene_id} has a multiline Pro text overlay."
                )
            if overlay_text:
                visible_text = " ".join(
                    detect_visible_text(clip.image_path)
                ).casefold()
                if overlay_text.casefold() in visible_text:
                    overlay_text = ""
            direction = ProSceneDirection(
                scene_id=scene.scene_id,
                start_seconds=clip.start_seconds,
                duration_seconds=clip.duration_seconds,
                incoming_transition=transition,
                transition_duration_seconds=transition_duration,
                overlay_text=overlay_text,
                overlay_position=scene.callout_position or "top_center",
            )
            directions.append(direction)

            cue = self._sound_cue(
                transition=transition,
                narration=scene.narration,
            )
            if cue is not None:
                effect = self._select_sound_effect(effects, cue)
                if effect is not None:
                    sound_events.append(
                        ProSoundEffectEvent(
                            file_path=str(effect[1]),
                            start_seconds=clip.start_seconds,
                            volume=self.SOUND_EFFECT_VOLUME,
                            cue=cue,
                        )
                    )

        return ProEditPlan(
            topic=storyboard.topic,
            total_duration_seconds=assembly_plan.total_duration_seconds,
            scenes=directions,
            sound_effects=sound_events,
        )

    @staticmethod
    def save_plan(plan: ProEditPlan, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        return target

    @staticmethod
    def _load_sound_effects(
        directory: str | Path,
    ) -> list[tuple[SoundEffectDefinition, Path]]:
        root = Path(directory)
        manifest_path = root / "manifest.json"
        if not root.is_dir():
            raise FileNotFoundError(
                f"Pro sound-effects directory was not found: {root}"
            )
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"Pro sound-effects manifest was not found: {manifest_path}"
            )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_effects = manifest.get("effects") if isinstance(manifest, dict) else None
        if not isinstance(raw_effects, list) or not raw_effects:
            raise ValueError("Pro sound-effects manifest must contain a non-empty effects list.")

        effects: list[tuple[SoundEffectDefinition, Path]] = []
        seen_files: set[str] = set()
        for raw_effect in raw_effects:
            effect = SoundEffectDefinition.model_validate(raw_effect)
            relative = _safe_relative_path(effect.file)
            if relative.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
                raise ValueError(
                    f"Unsupported sound-effects file type: {relative.as_posix()}"
                )
            normalized = relative.as_posix()
            if normalized in seen_files:
                raise ValueError(f"Duplicate sound-effects manifest entry: {normalized}")
            seen_files.add(normalized)
            path = root.joinpath(*relative.parts)
            if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
                raise FileNotFoundError(
                    f"Sound effect is missing, empty, or unsafe: {path}"
                )
            effects.append((effect, path))
        return effects

    @classmethod
    def _sound_cue(
        cls,
        *,
        transition: Transition,
        narration: str,
    ) -> str | None:
        if transition == "fade":
            return "transition"
        normalized = narration.casefold()
        for cue, keywords in cls.CUE_KEYWORDS.items():
            if any(keyword in normalized for keyword in keywords):
                return cue
        return None

    @staticmethod
    def _select_sound_effect(
        effects: list[tuple[SoundEffectDefinition, Path]],
        cue: str,
    ) -> tuple[SoundEffectDefinition, Path] | None:
        matching = [
            item
            for item in effects
            if cue in {tag.strip().casefold() for tag in item[0].tags}
            or (cue == "transition" and "whoosh" in {
                tag.strip().casefold() for tag in item[0].tags
            })
        ]
        return (
            min(matching, key=lambda item: item[0].file.casefold())
            if matching
            else None
        )


def prepare_sound_effects_archive(
    archive_path: str | Path,
    output_directory: str | Path,
) -> Path:
    """Safely extract a manifest-backed SFX ZIP into a new directory."""

    archive = Path(archive_path)
    if not archive.is_file():
        raise FileNotFoundError(f"Pro sound-effects archive was not found: {archive}")
    if archive.stat().st_size == 0:
        raise ValueError(f"Pro sound-effects archive is empty: {archive}")
    if archive.stat().st_size > MAX_SOUND_EFFECT_ARCHIVE_BYTES:
        raise ValueError("Pro sound-effects archive exceeds the 250 MiB limit.")

    target = Path(output_directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(
            f"Pro sound-effects output directory already exists: {target}"
        )

    with tempfile.TemporaryDirectory(
        dir=target.parent,
        prefix=f".{target.name}.",
    ) as temporary_name:
        temporary = Path(temporary_name)
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            files = [entry for entry in entries if not entry.is_dir()]
            if len(files) > MAX_SOUND_EFFECT_ARCHIVE_FILES:
                raise ValueError("Pro sound-effects archive contains too many files.")
            if sum(entry.file_size for entry in files) > MAX_SOUND_EFFECT_UNPACKED_BYTES:
                raise ValueError("Pro sound-effects archive exceeds the 500 MiB unpacked limit.")

            seen_paths: set[str] = set()
            for entry in entries:
                if entry.is_dir():
                    continue
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(
                        f"Pro sound-effects archive contains a symbolic link: {entry.filename}"
                    )
                relative = _safe_relative_path(entry.filename)
                normalized = relative.as_posix()
                if normalized in seen_paths:
                    raise ValueError(
                        f"Pro sound-effects archive contains a duplicate path: {normalized}"
                    )
                seen_paths.add(normalized)
                if (
                    normalized != "manifest.json"
                    and relative.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES
                ):
                    raise ValueError(
                        "Pro sound-effects ZIP may contain only manifest.json "
                        f"and supported audio files; found {entry.filename!r}."
                    )
                destination = temporary.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as input_file, destination.open("wb") as output_file:
                    shutil.copyfileobj(input_file, output_file)

        ProEditingDirector._load_sound_effects(temporary)
        temporary.replace(target)
    return target


def _safe_relative_path(value: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise ValueError(f"Unsafe Pro sound-effects path: {value!r}")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or PureWindowsPath(value).drive
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"Unsafe Pro sound-effects path: {value!r}")
    if any(":" in part for part in relative.parts):
        raise ValueError(f"Unsafe Pro sound-effects path: {value!r}")
    return relative
