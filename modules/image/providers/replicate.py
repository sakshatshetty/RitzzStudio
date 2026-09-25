"""Replicate-hosted FLUX Schnell image provider."""

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from modules.image.models import ImageGenerationRequest, ImageGenerationResult


load_dotenv()


class ReplicateFluxSchnellProvider:
    """Generate images with Black Forest Labs FLUX Schnell on Replicate."""

    MODEL_ENDPOINT = "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"
    POLL_INTERVAL_SECONDS = 2
    MAX_POLL_SECONDS = 300
    PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

    def __init__(self, api_token: str | None = None) -> None:
        self.api_token = api_token or os.getenv("REPLICATE_API_TOKEN")
        if not self.api_token:
            raise ValueError("REPLICATE_API_TOKEN is not configured.")

    def _json_request(self, url: str, method: str, body: dict[str, Any] | None = None,
                      prefer_wait: bool = False) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
            ),
        }
        if prefer_wait:
            headers["Prefer"] = "wait=60"
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Replicate API returned HTTP {exc.code}: {details}") from exc
        except URLError as exc:
            raise RuntimeError(f"Replicate API request failed: {exc.reason}") from exc
        if not isinstance(result, dict):
            raise ValueError("Replicate returned an invalid prediction response.")
        return result

    @staticmethod
    def _image_bytes(url: str) -> bytes:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
                )
            },
        )
        try:
            with urlopen(request, timeout=120) as response:
                return response.read()
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Could not download generated FLUX image: {exc}") from exc

    def _wait_for_completion(self, prediction: dict[str, Any]) -> dict[str, Any]:
        status = prediction.get("status")
        if status in {"succeeded", "failed", "canceled"}:
            return prediction
        get_url = prediction.get("urls", {}).get("get")
        if not get_url:
            raise ValueError("Replicate response is missing the prediction status URL.")

        deadline = time.monotonic() + self.MAX_POLL_SECONDS
        while time.monotonic() < deadline:
            time.sleep(self.POLL_INTERVAL_SECONDS)
            prediction = self._json_request(get_url, "GET")
            status = prediction.get("status")
            if status in {"succeeded", "failed", "canceled"}:
                return prediction
        raise TimeoutError("FLUX Schnell prediction did not finish within five minutes.")

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        try:
            prediction = self._json_request(
                self.MODEL_ENDPOINT,
                "POST",
                body={
                    "input": {
                        "prompt": request.prompt,
                        "go_fast": True,
                        "num_outputs": 1,
                        "aspect_ratio": "16:9",
                        "output_format": "png",
                        "num_inference_steps": 4,
                    }
                },
                prefer_wait=True,
            )
            prediction = self._wait_for_completion(prediction)
            if prediction.get("status") != "succeeded":
                raise RuntimeError(
                    f"FLUX Schnell prediction {prediction.get('status')}: "
                    f"{prediction.get('error') or 'unknown error'}"
                )
            output = prediction.get("output")
            image_url = output[0] if isinstance(output, list) and output else output
            if not isinstance(image_url, str) or not image_url.startswith("https://"):
                raise ValueError("FLUX Schnell returned no valid image URL.")
            image_data = self._image_bytes(image_url)
            if not image_data.startswith(self.PNG_SIGNATURE):
                raise ValueError("FLUX Schnell output is not a valid PNG image.")

            output_directory = Path(request.output_directory)
            output_directory.mkdir(parents=True, exist_ok=True)
            output_path = output_directory / f"{request.image_id}.png"
            output_path.write_bytes(image_data)
            return ImageGenerationResult(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider=request.provider,
                status="completed",
                file_path=str(output_path),
            )
        except Exception as exc:
            return ImageGenerationResult(
                image_id=request.image_id,
                scene_id=request.scene_id,
                provider=request.provider,
                status="failed",
                error_message=str(exc),
            )
