"""Technical and semantic checks for the 3-minute pilot."""

import base64
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.responses import ResponseTextConfigParam

from modules.storyboard.models import Storyboard
from modules.video.models import VideoAssemblyPlan
from modules.video.qa_models import (
    AudioImageMatchResult,
    PilotQAReport,
    QAStatus,
    RenderedVideoSemanticQAReport,
    SceneQAResult,
    TechnicalQAResult,
)
from modules.storyboard.editorial_qa import review_editorial_callouts

load_dotenv()


class SemanticReviewer(Protocol):
    def review(self, image_path: Path, scene: Any) -> SceneQAResult: ...


class AudioImageReviewer(Protocol):
    def match_audio_image(
        self,
        image_path: Path,
        scene: Any,
        start_seconds: float,
        end_seconds: float,
    ) -> AudioImageMatchResult: ...


_SCENE_REVIEW_RESPONSE_FORMAT: ResponseTextConfigParam = {
    "format": {
        "type": "json_schema",
        "name": "rendered_scene_review",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "narration_image": {
                    "type": "string",
                    "enum": ["PASS", "REVIEW", "FAIL"],
                },
                "narration_description": {
                    "type": "string",
                    "enum": ["PASS", "REVIEW", "FAIL"],
                },
                "editorial_context": {
                    "type": "string",
                    "enum": ["PASS", "REVIEW", "FAIL"],
                },
                "rationale": {"type": "string"},
                "correction_prompt": {"type": ["string", "null"]},
                "suggested_editorial_scene_id": {"type": ["string", "null"]},
            },
            "required": [
                "narration_image",
                "narration_description",
                "editorial_context",
                "rationale",
                "correction_prompt",
                "suggested_editorial_scene_id",
            ],
            "additionalProperties": False,
        },
    }
}


def _validate_png(path: Path) -> None:
    """Validate PNG chunks, checksums, and decompressed image data."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("image missing or empty")
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    offset, compressed, dimensions = 8, bytearray(), None
    saw_end = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("truncated PNG chunk")
        payload = data[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != expected_crc:
            raise ValueError("PNG chunk checksum mismatch")
        if kind == b"IHDR":
            if length != 13:
                raise ValueError("invalid PNG header")
            dimensions = struct.unpack(">II", payload[:8])
            bit_depth, color_type, compression, filtering, interlace = payload[8:13]
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
            bits = {1, 2, 4, 8, 16}
            if not dimensions or not channels or bit_depth not in bits or compression or filtering or interlace not in {0, 1}:
                raise ValueError("unsupported or invalid PNG header")
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            saw_end = True
            break
        offset = end
    if not saw_end or dimensions is None or not compressed:
        raise ValueError("incomplete PNG image")
    width, height = dimensions
    if width < 1 or height < 1 or width > 30000 or height > 30000:
        raise ValueError("invalid PNG dimensions")
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as exc:
        raise ValueError("invalid PNG image data") from exc
    if not raw:
        raise ValueError("empty PNG image data")


def _mp3_duration(path: Path) -> float:
    """Measure MPEG audio duration by counting valid MP3 frames."""
    data = path.read_bytes()
    offset = 0
    if data.startswith(b"ID3") and len(data) >= 10:
        size_bytes = data[6:10]
        tag_size = ((size_bytes[0] & 0x7f) << 21) | ((size_bytes[1] & 0x7f) << 14) | ((size_bytes[2] & 0x7f) << 7) | (size_bytes[3] & 0x7f)
        offset = 10 + tag_size
    bitrate_tables = {
        3: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
        2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
    }
    sample_rates = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}
    total_seconds = 0.0
    frame_count = 0
    while offset + 4 <= len(data):
        header = int.from_bytes(data[offset:offset + 4], "big")
        if header >> 21 != 0x7ff:
            offset += 1
            continue
        version = (header >> 19) & 3
        layer = (header >> 17) & 3
        bitrate_index = (header >> 12) & 15
        sample_index = (header >> 10) & 3
        if version == 1 or layer != 1 or bitrate_index in {0, 15} or sample_index == 3:
            offset += 1
            continue
        version_key = 3 if version == 3 else 2 if version == 2 else 0
        bitrate = bitrate_tables[3 if version_key == 3 else 2][bitrate_index] * 1000
        sample_rate = sample_rates[version_key][sample_index]
        padding = (header >> 9) & 1
        frame_length = ((144 if version_key == 3 else 72) * bitrate // sample_rate) + padding
        if frame_length < 24 or offset + frame_length > len(data):
            break
        total_seconds += (1152 if version_key == 3 else 576) / sample_rate
        frame_count += 1
        offset += frame_length
    if frame_count == 0:
        raise ValueError("Could not find valid MPEG audio frames.")
    return total_seconds


class OpenAIImageEditorialReviewer:
    """Review generated image relevance and editorial-word placement only."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        self.client = OpenAI(api_key=key)
        self.model = model or os.getenv("RITZZ_EDITORIAL_MODEL", "gpt-5.4-mini")

    def review(
        self,
        image_path: Path,
        scene: Any,
        editorial_candidates: list[dict[str, str]] | None = None,
    ) -> SceneQAResult:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        editorial = scene.text_overlay or "(none)"
        prompt = (
            "Review this frame from the rendered educational video at the midpoint of the listed scene. "
            "Check whether the visible scene matches its synchronized narration and whether the requested "
            "editorial word is contextually appropriate and visibly legible. If an editorial word is requested, "
            "mark editorial_context FAIL when it is clearly absent or incorrect, and REVIEW if it is too unclear "
            "to verify. Do not review research, script quality, style "
            "preferences, or production metadata. Return JSON keys narration_image, narration_description, "
            "editorial_context, rationale, correction_prompt, suggested_editorial_scene_id. Status values "
            "must be PASS, REVIEW, or FAIL. Use FAIL only for a clear mismatch; use REVIEW when uncertain. "
            "Set correction_prompt only when there is a concrete, actionable image correction; use null when "
            "the concern is uncertain or cannot be corrected from the image prompt alone. If the image is wrong, "
            "correction_prompt must describe a concrete image-only correction while "
            "preserving the requested style and character. If the word belongs on another supplied scene, "
            "set suggested_editorial_scene_id to that scene ID; otherwise use null.\n"
            "Current scene ID: " + scene.scene_id + "\nEditorial word: " + editorial +
            "\nNarration: " + scene.narration +
            "\nVisual description: " + scene.visual_description +
            "\nEditorial candidate scenes: " + json.dumps(editorial_candidates or [], ensure_ascii=False) +
            "\nImage prompt: " + scene.image_prompt
        )
        response = self.client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": "data:image/png;base64," + encoded, "detail": "low"},
            ]}],
            text=_SCENE_REVIEW_RESPONSE_FORMAT,
        )
        output_text = response.output_text
        if not output_text or not output_text.strip():
            response_status = getattr(response, "status", "unknown")
            incomplete_reason = getattr(
                getattr(response, "incomplete_details", None),
                "reason",
                None,
            )
            details = f"status={response_status}"
            if incomplete_reason:
                details += f", incomplete_reason={incomplete_reason}"
            raise ValueError(
                f"Semantic reviewer returned no structured output for "
                f"{scene.scene_id} ({details})."
            )
        try:
            result = json.loads(output_text)
            statuses = [result[k] for k in ("narration_image", "narration_description", "editorial_context")]
            if any(status not in {"PASS", "REVIEW", "FAIL"} for status in statuses):
                raise ValueError("invalid status")
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"Semantic reviewer returned invalid JSON for {scene.scene_id}.") from exc
        overall = "FAIL" if "FAIL" in statuses else "REVIEW" if "REVIEW" in statuses else "PASS"
        return SceneQAResult(scene_id=scene.scene_id, status=overall,
                             narration_image=result["narration_image"],
                             narration_description=result["narration_description"],
                             editorial_context=result["editorial_context"],
                             rationale=str(result.get("rationale", "")),
                             correction_prompt=result.get("correction_prompt"),
                             suggested_editorial_scene_id=result.get("suggested_editorial_scene_id"))

    def match_audio_image(self, image_path: Path, scene: Any, start_seconds: float,
                          end_seconds: float) -> AudioImageMatchResult:
        """Compare one actual scene image only with its synchronized narration beat."""
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = (
            "Judge only whether the visible content of this image is relevant to the narration heard "
            f"from {start_seconds:.3f}s to {end_seconds:.3f}s in the rendered video.\n"
            f"Narration: {scene.narration}\n"
            "Return only JSON: {\"status\":\"PASS|REVIEW|FAIL\",\"rationale\":\"brief reason\"}. "
            "PASS means the image clearly supports the narration; REVIEW means plausible or uncertain; "
            "FAIL means an obvious mismatch. Do not judge image quality, text, style, timing, or any other criterion."
        )
        response = self.client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": "data:image/png;base64," + encoded, "detail": "low"},
            ]}],
        )
        try:
            value = json.loads(response.output_text)
            status = value["status"]
            if status not in {"PASS", "REVIEW", "FAIL"}:
                raise ValueError("invalid status")
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"Audio-image reviewer returned invalid JSON for {scene.scene_id}.") from exc
        return AudioImageMatchResult(scene_id=scene.scene_id, status=status, narration=scene.narration,
                                     start_seconds=start_seconds, end_seconds=end_seconds,
                                     rationale=str(value.get("rationale", "")))


OpenAISemanticReviewer = OpenAIImageEditorialReviewer


class PilotVideoQA:
    LOUDNESS_TOLERANCE_LU = 1.5
    TRUE_PEAK_MEASUREMENT_TOLERANCE_DB = 0.1

    def run_audio_image_match(self, storyboard: Storyboard, plan: VideoAssemblyPlan,
                              reviewer: AudioImageReviewer) -> list[AudioImageMatchResult]:
        """Assess only whether each rendered scene image matches its narration beat."""
        scene_by_id = {scene.scene_id: scene for scene in storyboard.scenes}
        results = []
        for clip in plan.clips:
            scene = scene_by_id.get(clip.scene_id)
            if scene is None:
                results.append(AudioImageMatchResult(scene_id=clip.scene_id, status="FAIL", narration="",
                    start_seconds=clip.start_seconds, end_seconds=clip.start_seconds + clip.duration_seconds,
                    rationale="No corresponding narration scene."))
                continue
            results.append(reviewer.match_audio_image(Path(clip.image_path), scene, clip.start_seconds,
                                                       clip.start_seconds + clip.duration_seconds))
        return results

    def run_rendered_video_semantic(
        self,
        storyboard: Storyboard,
        plan: VideoAssemblyPlan,
        video_file: str | Path,
        reviewer: SemanticReviewer,
        *,
        ffmpeg_path: str | None = None,
    ) -> RenderedVideoSemanticQAReport:
        video_path = Path(video_file)
        if not video_path.is_file() or video_path.stat().st_size == 0:
            raise FileNotFoundError(f"Rendered video is missing or empty: {video_path}")
        executable = ffmpeg_path or os.getenv("RITZZ_FFMPEG_PATH") or shutil.which("ffmpeg")
        if not executable:
            raise FileNotFoundError("FFmpeg is required to sample rendered video frames.")

        scenes = {scene.scene_id: scene for scene in storyboard.scenes}
        results: list[SceneQAResult] = []
        with tempfile.TemporaryDirectory(prefix="ritzz_rendered_qa_") as temporary:
            directory = Path(temporary)
            for clip in plan.clips:
                scene = scenes.get(clip.scene_id)
                if scene is None:
                    results.append(
                        SceneQAResult(
                            scene_id=clip.scene_id,
                            status="FAIL",
                            narration_image="FAIL",
                            narration_description="FAIL",
                            editorial_context="FAIL",
                            rationale="Rendered scene has no matching storyboard narration.",
                        )
                    )
                    continue

                frame_file = directory / f"{clip.scene_id}.png"
                midpoint = clip.start_seconds + clip.duration_seconds / 2
                command = [
                    executable,
                    "-v", "error",
                    "-ss", f"{midpoint:.3f}",
                    "-i", str(video_path),
                    "-frames:v", "1",
                    "-update", "1",
                    "-y", str(frame_file),
                ]
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if completed.returncode != 0 or not frame_file.is_file() or frame_file.stat().st_size == 0:
                    raise RuntimeError(
                        f"Could not extract rendered frame for {clip.scene_id} "
                        f"at {midpoint:.3f}s: {completed.stderr.strip()}"
                    )
                result = reviewer.review(frame_file, scene)
                if result.scene_id != clip.scene_id:
                    raise ValueError(
                        f"Semantic reviewer returned {result.scene_id} for {clip.scene_id}."
                    )
                results.append(result)

        overall: QAStatus = (
            "FAIL"
            if any(result.status == "FAIL" for result in results)
            else "REVIEW"
            if not results or any(result.status == "REVIEW" for result in results)
            else "PASS"
        )
        return RenderedVideoSemanticQAReport(status=overall, results=results)

    def run_technical(self, storyboard: Storyboard, plan: VideoAssemblyPlan,
                      audio_file: str | Path, video_file: str | Path | None = None,
                      audio_duration: float | None = None,
                      video_duration: float | None = None) -> TechnicalQAResult:
        issues: list[str] = []
        checks: dict[str, QAStatus] = {}
        image_ok = True
        order_ok = len(storyboard.scenes) == len(plan.clips)
        no_gap = True
        monotonic = True
        durations_ok = True
        drift = 0.0
        if not order_ok:
            issues.append("Storyboard and render plan scene counts differ.")
        for i, (scene, clip) in enumerate(zip(storyboard.scenes, plan.clips)):
            if scene.scene_id != clip.scene_id:
                order_ok = False
                issues.append(f"Scene order mismatch at {scene.scene_id}.")
            try:
                _validate_png(Path(clip.image_path))
            except (OSError, ValueError) as exc:
                image_ok = False
                issues.append(f"{scene.scene_id}: {exc}")
            if not math.isfinite(clip.start_seconds) or not math.isfinite(clip.duration_seconds) or clip.duration_seconds <= 0:
                durations_ok = False
                issues.append(f"{scene.scene_id}: invalid scene timestamps or duration.")
            if i:
                previous = plan.clips[i - 1]
                delta = clip.start_seconds - (previous.start_seconds + previous.duration_seconds)
                if abs(delta) > 0.01:
                    no_gap = False
                    issues.append(f"{scene.scene_id}: timeline gap/overlap {delta:+.3f}s.")
            monotonic &= i == 0 or clip.start_seconds >= plan.clips[i - 1].start_seconds
            drift = max(drift, abs(scene.start_seconds - clip.start_seconds))
        audio_path = Path(audio_file)
        audio_ok = audio_path.is_file() and audio_path.stat().st_size > 0
        if audio_duration is None and audio_ok:
            try:
                from modules.video.render_engine import FFmpegVideoRenderer
                audio_duration = FFmpegVideoRenderer()._probe_media(audio_path)["duration_seconds"]
            except FileNotFoundError:
                try:
                    audio_duration = _mp3_duration(audio_path)
                except ValueError:
                    audio_duration = None
        audio_ok &= audio_duration is not None and audio_duration > 0
        duration_ok = bool(audio_ok and audio_duration is not None and abs(plan.total_duration_seconds - audio_duration) <= 0.25)
        video_ok = False
        if video_file is not None:
            video_path = Path(video_file)
            if video_duration is None and video_path.is_file():
                from modules.video.render_engine import FFmpegVideoRenderer
                probe = FFmpegVideoRenderer()._probe_media(video_path)
                video_duration = probe["duration_seconds"]
                video_ok = probe["has_video"] and probe["has_audio"] and video_path.stat().st_size > 0
            elif video_path.is_file() and video_duration is not None:
                video_ok = video_path.stat().st_size > 0
            video_ok &= video_duration is not None and audio_duration is not None and abs(video_duration - audio_duration) <= 0.25
        loudness_check: QAStatus = "REVIEW"
        integrated_lufs: float | None = None
        true_peak_dbtp: float | None = None
        target_lufs = -14.0
        true_peak_ceiling_dbtp = -1.0
        if video_file is None:
            issues.append(
                "Integrated loudness and true peak are unavailable until the video is rendered."
            )
        else:
            from modules.video.render_engine import FFmpegVideoRenderer

            try:
                renderer = FFmpegVideoRenderer()
                target_lufs = renderer.audio_target_lufs
                true_peak_ceiling_dbtp = renderer.audio_true_peak_ceiling_dbtp
                measurement = renderer.measure_audio_loudness(video_file)
                integrated_lufs = measurement.integrated_lufs
                true_peak_dbtp = measurement.true_peak_dbtp
                loudness_check = (
                    "PASS"
                    if abs(integrated_lufs - target_lufs)
                    <= self.LOUDNESS_TOLERANCE_LU
                    and true_peak_dbtp
                    <= true_peak_ceiling_dbtp
                    + self.TRUE_PEAK_MEASUREMENT_TOLERANCE_DB
                    else "REVIEW"
                )
                issues.append(
                    "Rendered audio loudness: "
                    f"{integrated_lufs:.1f} LUFS integrated "
                    f"(target {target_lufs:.1f} ±"
                    f"{self.LOUDNESS_TOLERANCE_LU:.1f} LU); "
                    f"true peak {true_peak_dbtp:.1f} dBTP "
                    f"(ceiling {true_peak_ceiling_dbtp:.1f} dBTP)."
                )
                if loudness_check != "PASS":
                    issues.append(
                        "Rendered audio loudness or true peak is outside the "
                        "configured target range; human review is required."
                    )
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                issues.append(
                    "Integrated loudness and true peak could not be measured; "
                    f"human review is required. {exc}"
                )
        editorial_qa = review_editorial_callouts(storyboard.scenes)
        if editorial_qa.status == "REVIEW":
            issues.extend(editorial_qa.findings)
        checks.update(
            images="PASS" if image_ok else "FAIL",
            audio="PASS" if audio_ok else "FAIL",
            scene_order="PASS" if order_ok else "FAIL",
            timestamps_monotonic="PASS" if monotonic else "FAIL",
            no_gaps_or_overlaps="PASS" if no_gap else "FAIL",
            scene_durations="PASS" if durations_ok else "FAIL",
            duration_consistency="PASS" if duration_ok else "FAIL",
            video=(
                "PASS"
                if video_ok
                else "REVIEW"
                if video_file is None
                else "FAIL"
            ),
            timestamp_coverage=(
                "PASS" if order_ok and durations_ok and no_gap else "FAIL"
            ),
            timeline_drift="PASS" if drift <= 0.5 else "REVIEW",
            audio_loudness=loudness_check,
            editorial_callouts=editorial_qa.status,
        )
        if not audio_ok:
            issues.append("Audio file missing, empty, or duration unavailable.")
        if not duration_ok:
            issues.append("Assembly duration does not match audio duration.")
        if not video_ok:
            issues.append(
                "Rendered video missing or its duration/streams do not match audio."
            )
        failed = any(v == "FAIL" for v in checks.values())
        status = "FAIL" if failed else "REVIEW" if any(v == "REVIEW" for v in checks.values()) else "PASS"
        return TechnicalQAResult(status=status, checks=checks, issues=issues, scene_count=len(plan.clips),
                                 audio_duration_seconds=float(audio_duration or 0), video_duration_seconds=video_duration,
                                 maximum_timeline_drift_seconds=drift,
                                 integrated_lufs=integrated_lufs,
                                 true_peak_dbtp=true_peak_dbtp,
                                 target_lufs=target_lufs,
                                 true_peak_ceiling_dbtp=true_peak_ceiling_dbtp,
                                 editorial_callouts=editorial_qa)

    def run_semantic(self, storyboard: Storyboard, plan: VideoAssemblyPlan,
                     reviewer: SemanticReviewer) -> list[SceneQAResult]:
        by_id = {scene.scene_id: scene for scene in storyboard.scenes}
        results = []
        for clip in plan.clips:
            scene = by_id.get(clip.scene_id)
            if scene is None:
                results.append(SceneQAResult(scene_id=clip.scene_id, status="FAIL", narration_image="FAIL",
                    narration_description="FAIL", editorial_context="FAIL", rationale="Scene missing from storyboard."))
            else:
                results.append(reviewer.review(Path(clip.image_path), scene))
        return results

    @staticmethod
    def save(report: PilotQAReport, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return output
