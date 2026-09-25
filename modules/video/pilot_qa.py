"""Technical and semantic checks for the 3-minute pilot."""

import base64
import json
import math
import os
import struct
import zlib
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv
from openai import OpenAI

from modules.storyboard.models import Storyboard
from modules.video.models import VideoAssemblyPlan
from modules.video.qa_models import AudioImageMatchResult, PilotQAReport, SceneQAResult, TechnicalQAResult

load_dotenv()


class SemanticReviewer(Protocol):
    def review(self, image_path: Path, scene: Any) -> SceneQAResult: ...


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


class OpenAISemanticReviewer:
    """Scene review using the existing OpenAI account and a vision model."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        self.client = OpenAI(api_key=key)
        self.model = model or os.getenv("RITZZ_EDITORIAL_MODEL", "gpt-5.4-mini")

    def review(self, image_path: Path, scene: Any) -> SceneQAResult:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        editorial = scene.text_overlay or "(none)"
        prompt = (
            "Review this generated illustration for an educational video. Compare the actual image with "
            "the narration, visual description, and embedded editorial word. Return only JSON with keys "
            "narration_image, narration_description, editorial_context, rationale. Each status must be "
            "PASS, REVIEW, or FAIL. Use REVIEW when uncertain; FAIL only for clear contradiction or mismatch. "
            "Editorial word: " + editorial + "\nNarration: " + scene.narration +
            "\nVisual description: " + scene.visual_description + "\nImage prompt: " + scene.image_prompt
        )
        response = self.client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": "data:image/png;base64," + encoded, "detail": "low"},
            ]}],
        )
        try:
            result = json.loads(response.output_text)
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
                             rationale=str(result.get("rationale", "")))

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


class PilotVideoQA:
    def run_audio_image_match(self, storyboard: Storyboard, plan: VideoAssemblyPlan,
                              reviewer: OpenAISemanticReviewer) -> list[AudioImageMatchResult]:
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

    def run_technical(self, storyboard: Storyboard, plan: VideoAssemblyPlan,
                      audio_file: str | Path, video_file: str | Path | None = None,
                      audio_duration: float | None = None,
                      video_duration: float | None = None) -> TechnicalQAResult:
        issues: list[str] = []
        checks: dict[str, str] = {}
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
        checks.update(images="PASS" if image_ok else "FAIL", audio="PASS" if audio_ok else "FAIL",
                      scene_order="PASS" if order_ok else "FAIL", timestamps_monotonic="PASS" if monotonic else "FAIL",
                      no_gaps_or_overlaps="PASS" if no_gap else "FAIL", scene_durations="PASS" if durations_ok else "FAIL",
                      duration_consistency="PASS" if duration_ok else "FAIL", video="PASS" if video_ok else ("REVIEW" if video_file is None else "FAIL"),
                      timestamp_coverage="PASS" if order_ok and durations_ok and no_gap else "FAIL",
                      timeline_drift="PASS" if drift <= 0.5 else "REVIEW")
        if not audio_ok: issues.append("Audio file missing, empty, or duration unavailable.")
        if not duration_ok: issues.append("Assembly duration does not match audio duration.")
        if not video_ok: issues.append("Rendered video missing or its duration/streams do not match audio.")
        failed = any(v == "FAIL" for v in checks.values())
        status = "FAIL" if failed else "REVIEW" if any(v == "REVIEW" for v in checks.values()) else "PASS"
        return TechnicalQAResult(status=status, checks=checks, issues=issues, scene_count=len(plan.clips),
                                 audio_duration_seconds=float(audio_duration or 0), video_duration_seconds=video_duration,
                                 maximum_timeline_drift_seconds=drift)

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
