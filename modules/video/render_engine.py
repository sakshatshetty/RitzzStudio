import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from modules.video.engine import VideoAssemblyEngine
from modules.video.models import VideoAssemblyPlan
from modules.video.motion_engine import VideoMotionEngine
from modules.video.motion_models import VideoMotionPlan
from modules.video.render_models import (
    AudioLoudnessMeasurement,
    VideoRenderRequest,
    VideoRenderResult,
)


class FFmpegVideoRenderer:
    """
    Renders the Ritzz video using FFmpeg.

    This renderer:
    - Uses the synchronized video timeline.
    - Applies zoom/pan motion.
    - Uses hard cuts between scenes.
    - Adds narration audio.
    - Supports configurable output resolution and FPS.
    - Validates the final MP4 with ffprobe.
    """

    DEFAULT_CODEC = "libx264"
    DEFAULT_PRESET = "medium"
    DEFAULT_VIDEO_BITRATE = "10M"
    DEFAULT_AUDIO_CODEC = "aac"
    DEFAULT_AUDIO_BITRATE = "192k"
    DEFAULT_AUDIO_TARGET_LUFS = -14.0
    DEFAULT_AUDIO_TRUE_PEAK_CEILING_DBTP = -1.0
    AUDIO_LOUDNESS_RANGE_LU = 11.0
    AUDIO_TRUE_PEAK_CODEC_HEADROOM_DB = 1.0
    VIDEO_BITRATE_TOLERANCE = 0.20

    DURATION_TOLERANCE_SECONDS = 0.25
    _EBU_R128_SUMMARY_PATTERN = re.compile(
        r"Integrated loudness:\s*I:\s*"
        r"(-?(?:\d+(?:\.\d*)?|\.\d+))\s*LUFS"
        r".*?True peak:\s*Peak:\s*"
        r"(-?(?:\d+(?:\.\d*)?|\.\d+))\s*dBFS",
        re.DOTALL,
    )

    def __init__(
        self,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
    ) -> None:
        self.ffmpeg_path = (
            ffmpeg_path
            or os.getenv("RITZZ_FFMPEG_PATH")
            or shutil.which("ffmpeg")
        )

        self.ffprobe_path = (
            ffprobe_path
            or os.getenv("RITZZ_FFPROBE_PATH")
            or shutil.which("ffprobe")
        )
        self.video_bitrate = os.getenv(
            "RITZZ_VIDEO_BITRATE",
            self.DEFAULT_VIDEO_BITRATE,
        ).strip()
        self.video_bitrate_bps = self._parse_bitrate(self.video_bitrate)
        self.audio_target_lufs = self._parse_audio_setting(
            "RITZZ_AUDIO_TARGET_LUFS",
            self.DEFAULT_AUDIO_TARGET_LUFS,
            minimum=-70.0,
            maximum=-5.0,
        )
        self.audio_true_peak_ceiling_dbtp = self._parse_audio_setting(
            "RITZZ_AUDIO_TRUE_PEAK_CEILING_DBTP",
            self.DEFAULT_AUDIO_TRUE_PEAK_CEILING_DBTP,
            minimum=-9.0,
            maximum=0.0,
        )

        if not self.ffmpeg_path:
            raise FileNotFoundError(
                "FFmpeg executable was not found. "
                "Install FFmpeg or configure "
                "RITZZ_FFMPEG_PATH."
            )

        if not self.ffprobe_path:
            raise FileNotFoundError(
                "ffprobe executable was not found. "
                "Install FFmpeg or configure "
                "RITZZ_FFPROBE_PATH."
            )

    @staticmethod
    def _parse_bitrate(value: str) -> int:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmM]?)\s*", value)
        if match is None:
            raise ValueError(
                "RITZZ_VIDEO_BITRATE must be a positive number optionally "
                "followed by k or M, for example 10M."
            )
        magnitude = float(match.group(1))
        multiplier = {"": 1, "k": 1_000, "m": 1_000_000}[
            match.group(2).lower()
        ]
        bitrate = int(magnitude * multiplier)
        if bitrate <= 0:
            raise ValueError("RITZZ_VIDEO_BITRATE must be greater than zero.")
        return bitrate

    @staticmethod
    def _parse_audio_setting(
        name: str,
        default: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number.") from exc
        if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
            raise ValueError(
                f"{name} must be between {minimum:g} and {maximum:g}."
            )
        return parsed

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def create_request(
        self,
        assembly_plan_file: str | Path,
        motion_plan_file: str | Path,
        output_file: str | Path,
        audio_file: str | Path | None = None,
    ) -> VideoRenderRequest:
        """
        Create a typed render request.
        """

        return VideoRenderRequest(
            assembly_plan_file=str(
                assembly_plan_file
            ),
            motion_plan_file=str(
                motion_plan_file
            ),
            output_file=str(
                output_file
            ),
            audio_file=(
                str(audio_file)
                if audio_file is not None
                else None
            ),
        )

    def run(
        self,
        request: VideoRenderRequest,
    ) -> VideoRenderResult:
        """
        Render a video and return a structured result.
        """

        try:
            assembly_plan = (
                VideoAssemblyEngine.load_plan(
                    request.assembly_plan_file
                )
            )

            motion_plan = (
                VideoMotionEngine.load_plan(
                    request.motion_plan_file
                )
            )

            audio_path = (
                Path(request.audio_file)
                if request.audio_file
                else self._get_audio_from_plan(
                    assembly_plan
                )
            )

            output_path = Path(
                request.output_file
            )

            self.render(
                assembly_plan=assembly_plan,
                motion_plan=motion_plan,
                audio_file=audio_path,
                output_file=output_path,
            )

            probe = self._probe_media(
                output_path
            )
            loudness = self.measure_audio_loudness(output_path)

            return VideoRenderResult(
                status="completed",
                output_file=str(
                    output_path
                ),
                duration_seconds=probe[
                    "duration_seconds"
                ],
                width=probe[
                    "width"
                ],
                height=probe[
                    "height"
                ],
                fps=probe[
                    "fps"
                ],
                file_size_bytes=(
                    output_path.stat().st_size
                ),
                integrated_lufs=loudness.integrated_lufs,
                true_peak_dbtp=loudness.true_peak_dbtp,
                error_message=None,
            )

        except Exception as exc:
            return VideoRenderResult(
                status="failed",
                output_file=None,
                duration_seconds=0,
                width=0,
                height=0,
                fps=0,
                file_size_bytes=0,
                integrated_lufs=None,
                true_peak_dbtp=None,
                error_message=str(exc),
            )

    def render(
        self,
        assembly_plan: VideoAssemblyPlan,
        motion_plan: VideoMotionPlan,
        audio_file: str | Path,
        output_file: str | Path,
    ) -> Path:
        """
        Render the synchronized plan to MP4.
        """

        self._validate_plans(
            assembly_plan,
            motion_plan,
        )

        audio_path = Path(
            audio_file
        )

        if not audio_path.exists():
            raise FileNotFoundError(
                f"Audio file not found: {audio_path}"
            )

        if not audio_path.is_file():
            raise ValueError(
                f"Audio path is not a file: {audio_path}"
            )

        if audio_path.stat().st_size <= 0:
            raise ValueError(
                f"Audio file is empty: {audio_path}"
            )

        audio_probe = self._probe_media(
            audio_path
        )

        audio_duration = (
            audio_probe["duration_seconds"]
        )

        if abs(
            audio_duration
            - assembly_plan.total_duration_seconds
        ) > self.DURATION_TOLERANCE_SECONDS:
            raise ValueError(
                "Audio duration does not match "
                "the synchronized video duration. "
                f"Audio={audio_duration:.3f}s, "
                f"Plan={assembly_plan.total_duration_seconds:.3f}s."
            )

        image_paths = [
            Path(clip.image_path)
            for clip in assembly_plan.clips
        ]

        for image_path in image_paths:
            self._validate_image(
                image_path
            )

        output_path = Path(
            output_file
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        filter_script = self.build_filter_script(
            assembly_plan,
            motion_plan,
        )

        command = [
            self.ffmpeg_path,
            "-y",
        ]

        for image_path in image_paths:
            command.extend(
                [
                    "-i",
                    str(image_path),
                ]
            )

        audio_input_index = len(
            image_paths
        )

        command.extend(
            [
                "-i",
                str(audio_path),

                "-filter_complex",
                filter_script,

                "-map",
                "[vout]",

                "-map",
                f"{audio_input_index}:a:0",

                "-af",
                self.build_audio_filter(),

                "-t",
                f"{assembly_plan.total_duration_seconds:.3f}",

                "-c:v",
                self.DEFAULT_CODEC,

                "-preset",
                self.DEFAULT_PRESET,

                "-b:v",
                self.video_bitrate,

                "-minrate",
                self.video_bitrate,

                "-maxrate",
                self.video_bitrate,

                "-bufsize",
                str(self.video_bitrate_bps * 2),

                "-x264-params",
                "nal-hrd=cbr",

                "-pix_fmt",
                "yuv420p",

                "-c:a",
                self.DEFAULT_AUDIO_CODEC,

                "-b:a",
                self.DEFAULT_AUDIO_BITRATE,

                "-movflags",
                "+faststart",

                str(output_path),
            ]
        )

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                "FFmpeg rendering failed.\n"
                f"Command: {' '.join(command)}\n"
                f"STDOUT:\n{completed.stdout}\n"
                f"STDERR:\n{completed.stderr}"
            )

        if not output_path.exists():
            raise RuntimeError(
                "FFmpeg completed but the output "
                f"file was not created: {output_path}"
            )

        if output_path.stat().st_size <= 0:
            raise RuntimeError(
                "FFmpeg created an empty output file: "
                f"{output_path}"
            )

        self._validate_rendered_output(
            output_path,
            assembly_plan,
        )

        return output_path

    def build_audio_filter(self) -> str:
        encoding_peak_target = max(
            -9.0,
            self.audio_true_peak_ceiling_dbtp
            - self.AUDIO_TRUE_PEAK_CODEC_HEADROOM_DB,
        )
        return (
            "acompressor=threshold=0.05:ratio=20:attack=5:release=100:makeup=1,"
            f"loudnorm=I={self.audio_target_lufs:g}:"
            f"TP={encoding_peak_target:g}:"
            f"LRA={self.AUDIO_LOUDNESS_RANGE_LU:g}"
        )

    def measure_audio_loudness(
        self,
        media_file: str | Path,
    ) -> AudioLoudnessMeasurement:
        command = [
            self.ffmpeg_path,
            "-hide_banner",
            "-nostats",
            "-i",
            str(media_file),
            "-map",
            "0:a:0",
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"FFmpeg loudness measurement failed for {media_file}.\n"
                f"{completed.stderr}"
            )
        match = self._EBU_R128_SUMMARY_PATTERN.search(completed.stderr)
        if match is None:
            raise ValueError(
                "FFmpeg did not report finite integrated loudness and true peak; "
                "the audio may be silent or too short to measure."
            )
        integrated_lufs, true_peak_dbtp = map(float, match.groups())
        if not math.isfinite(integrated_lufs) or not math.isfinite(true_peak_dbtp):
            raise ValueError(
                "FFmpeg reported non-finite integrated loudness or true peak."
            )
        return AudioLoudnessMeasurement(
            integrated_lufs=integrated_lufs,
            true_peak_dbtp=true_peak_dbtp,
        )

    # -----------------------------------------------------------------
    # Filter generation
    # -----------------------------------------------------------------

    def build_filter_script(
        self,
        assembly_plan: VideoAssemblyPlan,
        motion_plan: VideoMotionPlan,
    ) -> str:
        """
        Build the FFmpeg filter graph.

        Every scene is rendered independently and then
        concatenated using normal hard cuts.
        """

        self._validate_plans(
            assembly_plan,
            motion_plan,
        )

        filters: list[str] = []

        video_labels: list[str] = []

        for index, (
            clip,
            instruction,
        ) in enumerate(
            zip(
                assembly_plan.clips,
                motion_plan.instructions,
            )
        ):
            input_label = (
                f"[{index}:v]"
            )

            output_label = (
                f"[v{index}]"
            )

            video_labels.append(
                output_label
            )

            frames = max(
                1,
                int(
                    round(
                        clip.duration_seconds
                        * assembly_plan.fps
                    )
                ),
            )

            denominator = max(
                frames - 1,
                1,
            )

            zoom_expression = (
                f"{instruction.zoom_start:.6f}"
                f"+("
                f"{instruction.zoom_end:.6f}"
                f"-"
                f"{instruction.zoom_start:.6f}"
                f")*on/{denominator}"
            )

            x_expression = (
                f"(iw-iw/zoom)*("
                f"{instruction.position_x_start:.6f}"
                f"+("
                f"{instruction.position_x_end:.6f}"
                f"-"
                f"{instruction.position_x_start:.6f}"
                f")*on/{denominator}"
                f")"
            )

            y_expression = (
                f"(ih-ih/zoom)*("
                f"{instruction.position_y_start:.6f}"
                f"+("
                f"{instruction.position_y_end:.6f}"
                f"-"
                f"{instruction.position_y_start:.6f}"
                f")*on/{denominator}"
                f")"
            )

            duration = (
                f"{clip.duration_seconds:.6f}"
            )

            if instruction.motion == "static":
                filter_expression = (
                    f"{input_label}"
                    f"loop=loop=-1:size=1:start=0,"
                    f"scale="
                    f"{assembly_plan.width}:"
                    f"{assembly_plan.height}:"
                    f"force_original_aspect_ratio=decrease,"
                    f"pad="
                    f"{assembly_plan.width}:"
                    f"{assembly_plan.height}:"
                    f"(ow-iw)/2:"
                    f"(oh-ih)/2,"
                    f"setsar=1,"
                    f"fps={assembly_plan.fps},"
                    f"trim=duration={duration},"
                    f"setpts=PTS-STARTPTS"
                    f"{output_label}"
                )
                filters.append(filter_expression)
                continue

            filter_expression = (
                f"{input_label}"
                f"scale="
                f"{assembly_plan.width}:"
                f"{assembly_plan.height}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad="
                f"{assembly_plan.width}:"
                f"{assembly_plan.height}:"
                f"(ow-iw)/2:"
                f"(oh-ih)/2,"
                f"setsar=1,"
                f"zoompan="
                f"z='{zoom_expression}':"
                f"x='{x_expression}':"
                f"y='{y_expression}':"
                f"d={frames}:"
                f"s="
                f"{assembly_plan.width}x"
                f"{assembly_plan.height}:"
                f"fps={assembly_plan.fps},"
                f"trim="
                f"duration={duration},"
                f"setpts=PTS-STARTPTS"
                f"{output_label}"
            )

            filters.append(
                filter_expression
            )

        concat_inputs = "".join(
            video_labels
        )

        filters.append(
            f"{concat_inputs}"
            f"concat="
            f"n={len(video_labels)}:"
            f"v=1:"
            f"a=0"
            f"[vconcat]"
        )

        filters.append(
            "[vconcat]"
            "format=yuv420p"
            "[vout]"
        )

        return ";\n".join(
            filters
        ) + ";\n"

    # -----------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------

    @staticmethod
    def _validate_plans(
        assembly_plan: VideoAssemblyPlan,
        motion_plan: VideoMotionPlan,
    ) -> None:
        """
        Validate that the assembly and motion plans
        represent exactly the same timeline.
        """

        if assembly_plan.topic != motion_plan.topic:
            raise ValueError(
                "Assembly plan topic does not match "
                "motion plan topic."
            )

        if len(
            assembly_plan.clips
        ) != len(
            motion_plan.instructions
        ):
            raise ValueError(
                "Assembly clip count does not match "
                "motion instruction count."
            )

        if (
            assembly_plan.width
            != motion_plan.width
        ):
            raise ValueError(
                "Assembly width does not match "
                "motion plan width."
            )

        if (
            assembly_plan.height
            != motion_plan.height
        ):
            raise ValueError(
                "Assembly height does not match "
                "motion plan height."
            )

        if (
            assembly_plan.fps
            != motion_plan.fps
        ):
            raise ValueError(
                "Assembly FPS does not match "
                "motion plan FPS."
            )

        if abs(
            assembly_plan.total_duration_seconds
            - motion_plan.total_duration_seconds
        ) > 0.01:
            raise ValueError(
                "Assembly duration does not match "
                "motion plan duration."
            )

        for index, (
            clip,
            instruction,
        ) in enumerate(
            zip(
                assembly_plan.clips,
                motion_plan.instructions,
            )
        ):
            if (
                clip.scene_id
                != instruction.scene_id
            ):
                raise ValueError(
                    "Scene ordering mismatch "
                    f"at index {index}."
                )

            if abs(
                clip.start_seconds
                - instruction.start_seconds
            ) > 0.01:
                raise ValueError(
                    f"{clip.scene_id} start time does not "
                    "match motion plan."
                )

            if abs(
                clip.duration_seconds
                - instruction.duration_seconds
            ) > 0.01:
                raise ValueError(
                    f"{clip.scene_id} duration does not "
                    "match motion plan."
                )

    @staticmethod
    def _validate_image(
        image_path: Path,
    ) -> None:
        """
        Validate that an image exists and is non-empty.
        """

        if not image_path.exists():
            raise FileNotFoundError(
                f"Image file not found: {image_path}"
            )

        if not image_path.is_file():
            raise ValueError(
                f"Image path is not a file: {image_path}"
            )

        if image_path.stat().st_size <= 0:
            raise ValueError(
                f"Image file is empty: {image_path}"
            )

    @staticmethod
    def _get_audio_from_plan(
        assembly_plan: VideoAssemblyPlan,
    ) -> Path:
        """
        Get the audio file configured in the assembly plan.
        """

        if not assembly_plan.audio_path:
            raise ValueError(
                "No audio file was supplied and the "
                "assembly plan does not contain an audio path."
            )

        return Path(
            assembly_plan.audio_path
        )

    # -----------------------------------------------------------------
    # FFprobe
    # -----------------------------------------------------------------

    def _probe_media(
        self,
        media_file: str | Path,
    ) -> dict[str, Any]:
        """
        Probe a media file using ffprobe.
        """

        path = Path(
            media_file
        )

        command = [
            self.ffprobe_path,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                "ffprobe failed for "
                f"{path}.\n{completed.stderr}"
            )

        try:
            data = json.loads(
                completed.stdout
            )
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "ffprobe returned invalid JSON."
            ) from exc

        streams = data.get(
            "streams",
            [],
        )

        format_data = data.get(
            "format",
            {},
        )

        duration = float(
            format_data.get(
                "duration",
                0,
            )
        )

        video_stream = next(
            (
                stream
                for stream in streams
                if stream.get("codec_type")
                == "video"
            ),
            None,
        )

        audio_stream = next(
            (
                stream
                for stream in streams
                if stream.get("codec_type")
                == "audio"
            ),
            None,
        )

        width = int(
            video_stream.get(
                "width",
                0,
            )
        ) if video_stream else 0

        height = int(
            video_stream.get(
                "height",
                0,
            )
        ) if video_stream else 0

        fps = 0.0

        if video_stream:
            fps_text = video_stream.get(
                "r_frame_rate",
                "0/1",
            )

            try:
                numerator, denominator = (
                    fps_text.split("/")
                )

                fps = (
                    float(numerator)
                    / float(denominator)
                )
            except (
                ValueError,
                ZeroDivisionError,
            ):
                fps = 0.0

        return {
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "fps": fps,
            "video_codec_name": (
                video_stream.get("codec_name")
                if video_stream
                else None
            ),
            "video_bit_rate_bps": self._parse_probe_integer(
                video_stream.get("bit_rate")
                if video_stream
                else None
            ),
            "audio_duration_seconds": self._parse_probe_float(
                audio_stream.get("duration")
                if audio_stream
                else None
            ),
            "audio_channels": self._parse_probe_integer(
                audio_stream.get("channels")
                if audio_stream
                else None
            ),
            "has_video": (
                video_stream is not None
            ),
            "has_audio": (
                audio_stream is not None
            ),
        }

    def _validate_rendered_output(
        self,
        output_file: Path,
        assembly_plan: VideoAssemblyPlan,
    ) -> None:
        """
        Validate the completed MP4.
        """

        probe = self._probe_media(
            output_file
        )

        if not probe["has_video"]:
            raise ValueError(
                "Rendered output does not contain "
                "a video stream."
            )

        if not probe["has_audio"]:
            raise ValueError(
                "Rendered output does not contain "
                "an audio stream."
            )

        if probe["video_codec_name"] != "h264":
            raise ValueError(
                "Rendered video codec must be H.264; "
                f"received {probe['video_codec_name']}."
            )

        video_bit_rate = probe["video_bit_rate_bps"]
        minimum_bit_rate = int(
            self.video_bitrate_bps
            * (1 - self.VIDEO_BITRATE_TOLERANCE)
        )
        maximum_bit_rate = int(
            self.video_bitrate_bps
            * (1 + self.VIDEO_BITRATE_TOLERANCE)
        )
        if (
            video_bit_rate is None
            or not minimum_bit_rate <= video_bit_rate <= maximum_bit_rate
        ):
            raise ValueError(
                "Rendered video bitrate is outside the configured range "
                f"({minimum_bit_rate}–{maximum_bit_rate} bps): "
                f"{video_bit_rate}."
            )

        if probe["width"] != (
            assembly_plan.width
        ):
            raise ValueError(
                "Rendered video width does not match "
                "assembly plan."
            )

        if probe["height"] != (
            assembly_plan.height
        ):
            raise ValueError(
                "Rendered video height does not match "
                "assembly plan."
            )

        if abs(
            probe["fps"]
            - assembly_plan.fps
        ) > 0.1:
            raise ValueError(
                "Rendered video FPS does not match "
                "assembly plan."
            )

        if abs(
            probe["duration_seconds"]
            - assembly_plan.total_duration_seconds
        ) > self.DURATION_TOLERANCE_SECONDS:
            raise ValueError(
                "Rendered video duration does not match "
                "assembly plan."
            )

        audio_duration = probe["audio_duration_seconds"]
        if (
            audio_duration is not None
            and abs(audio_duration - probe["duration_seconds"])
            > self.DURATION_TOLERANCE_SECONDS
        ):
            raise ValueError(
                "Rendered audio and video stream durations do not match."
            )

    @staticmethod
    def _parse_probe_integer(value: object) -> int | None:
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _parse_probe_float(value: object) -> float | None:
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
