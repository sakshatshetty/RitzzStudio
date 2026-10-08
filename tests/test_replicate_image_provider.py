import io
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.image.models import ImageGenerationRequest
from modules.image.providers.replicate import ReplicateFluxSchnellProvider

PNG_DATA = b"\x89PNG\r\n\x1a\nmock image data"


def _png_header(width: int, height: int) -> bytes:
    return ReplicateFluxSchnellProvider.PNG_SIGNATURE + b"\x00" * 8 + struct.pack(
        ">II",
        width,
        height,
    )


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


def test_generates_and_saves_png(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ReplicateFluxSchnellProvider(api_token="test-token")
    monkeypatch.setattr(
        provider,
        "_normalize_image",
        lambda image_data, _width, _height: image_data,
    )
    prediction = {"status": "succeeded", "output": ["https://files.example/image.png"]}

    def fake_urlopen(request, timeout):
        if request.full_url == provider.MODEL_ENDPOINT:
            return io.BytesIO(json.dumps(prediction).encode())
        return io.BytesIO(PNG_DATA)

    with patch("modules.image.providers.replicate.urlopen", side_effect=fake_urlopen):
        result = provider.generate(create_request(tmp_path))

    assert result.status == "completed"
    assert result.provider == "replicate"
    assert result.file_path is not None
    output = Path(result.file_path)
    assert output.name == "scene_004.png"
    assert output.read_bytes() == PNG_DATA


def test_request_uses_trial_model_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ReplicateFluxSchnellProvider(api_token="test-token")
    normalized_dimensions = []

    def identity_normalizer(image_data, width, height):
        normalized_dimensions.append((width, height))
        return image_data

    monkeypatch.setattr(provider, "_normalize_image", identity_normalizer)
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
    assert normalized_dimensions == [(1536, 864)]


def test_normalizes_flux_output_to_requested_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ReplicateFluxSchnellProvider(api_token="test-token")
    output_bytes = _png_header(1536, 864)

    def fake_run(command, **_kwargs):
        assert command[command.index("-vf") + 1] == (
            "scale=1536:864:force_original_aspect_ratio=increase,"
            "crop=1536:864"
        )
        Path(command[-1]).write_bytes(output_bytes)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(
        "modules.image.providers.replicate.subprocess.run",
        fake_run,
    )

    normalized = provider._normalize_image(
        _png_header(1344, 768),
        1536,
        864,
    )

    assert normalized == output_bytes


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
    assert result.error_message is not None
    assert "not a valid PNG" in result.error_message
