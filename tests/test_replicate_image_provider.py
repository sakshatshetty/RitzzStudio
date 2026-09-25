import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from modules.image.models import ImageGenerationRequest
from modules.image.providers.replicate import ReplicateFluxSchnellProvider


PNG_DATA = b"\x89PNG\r\n\x1a\nmock image data"


def create_request(tmp_path: Path) -> ImageGenerationRequest:
    return ImageGenerationRequest(
        image_id="scene_004",
        scene_id="scene_004",
        prompt="Colorful pirate illustration with the word ICONIC.",
        provider="replicate",
        output_directory=str(tmp_path),
    )


def test_requires_replicate_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    with pytest.raises(ValueError, match="REPLICATE_API_TOKEN"):
        ReplicateFluxSchnellProvider()


def test_generates_and_saves_png(tmp_path: Path) -> None:
    provider = ReplicateFluxSchnellProvider(api_token="test-token")
    prediction = {"status": "succeeded", "output": ["https://files.example/image.png"]}

    def fake_urlopen(request, timeout):
        if request.full_url == provider.MODEL_ENDPOINT:
            return io.BytesIO(json.dumps(prediction).encode())
        return io.BytesIO(PNG_DATA)

    with patch("modules.image.providers.replicate.urlopen", side_effect=fake_urlopen):
        result = provider.generate(create_request(tmp_path))

    assert result.status == "completed"
    assert result.provider == "replicate"
    output = Path(result.file_path)
    assert output.name == "scene_004.png"
    assert output.read_bytes() == PNG_DATA


def test_request_uses_trial_model_settings(tmp_path: Path) -> None:
    provider = ReplicateFluxSchnellProvider(api_token="test-token")
    prediction = {"status": "succeeded", "output": ["https://files.example/image.png"]}
    captured = {}

    def fake_urlopen(request, timeout):
        if request.full_url == provider.MODEL_ENDPOINT:
            captured["request"] = request
            return io.BytesIO(json.dumps(prediction).encode())
        return io.BytesIO(PNG_DATA)

    with patch("modules.image.providers.replicate.urlopen", side_effect=fake_urlopen):
        provider.generate(create_request(tmp_path))

    request = captured["request"]
    assert request.get_header("Authorization") == "Bearer test-token"
    assert request.get_header("Prefer") == "wait=60"
    assert "Chrome/138.0.0.0" in request.get_header("User-agent")
    payload = json.loads(request.data.decode())
    assert payload["input"]["aspect_ratio"] == "16:9"
    assert payload["input"]["output_format"] == "png"
    assert payload["input"]["num_outputs"] == 1
    assert payload["input"]["num_inference_steps"] == 4


def test_rejects_non_png_output(tmp_path: Path) -> None:
    provider = ReplicateFluxSchnellProvider(api_token="test-token")
    prediction = {"status": "succeeded", "output": ["https://files.example/image.png"]}

    def fake_urlopen(request, timeout):
        if request.full_url == provider.MODEL_ENDPOINT:
            return io.BytesIO(json.dumps(prediction).encode())
        return io.BytesIO(b"not png")

    with patch("modules.image.providers.replicate.urlopen", side_effect=fake_urlopen):
        result = provider.generate(create_request(tmp_path))

    assert result.status == "failed"
    assert "not a valid PNG" in result.error_message
