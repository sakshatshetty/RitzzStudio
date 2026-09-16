import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from modules.image.models import ImageGenerationRequest
from modules.image.providers.openai import OpenAIImageProvider


def create_request(
    tmp_path: Path,
) -> ImageGenerationRequest:
    """Create a test image-generation request."""
    return ImageGenerationRequest(
        image_id="scene_001",
        scene_id="scene_001",
        prompt="Simple 2D stickman pirate on a ship.",
        provider="openai",
        output_directory=str(tmp_path),
    )


def create_openai_response(
    image_bytes: bytes = b"PNG_TEST_DATA",
) -> MagicMock:
    """Create a mocked OpenAI image response."""

    encoded = base64.b64encode(
        image_bytes
    ).decode("ascii")

    image_data = MagicMock()
    image_data.b64_json = encoded

    response = MagicMock()
    response.data = [image_data]

    return response


def test_provider_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "OPENAI_API_KEY",
        raising=False,
    )

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIImageProvider()


def test_provider_accepts_api_key() -> None:
    provider = OpenAIImageProvider(
        api_key="test-api-key",
    )

    assert provider.api_key == "test-api-key"
    assert provider.client is not None


def test_generate_success(
    tmp_path: Path,
) -> None:
    provider = OpenAIImageProvider(
        api_key="test-api-key",
    )

    response = create_openai_response(
        image_bytes=b"PNG_TEST_DATA",
    )

    provider.client.images.generate = MagicMock(
        return_value=response,
    )

    request = create_request(tmp_path)

    result = provider.generate(request)

    assert result.status == "completed"
    assert result.file_path is not None

    output_path = Path(result.file_path)

    assert output_path.exists()
    assert output_path.name == "scene_001.png"
    assert output_path.read_bytes() == b"PNG_TEST_DATA"


def test_generate_sends_expected_parameters(
    tmp_path: Path,
) -> None:
    provider = OpenAIImageProvider(
        api_key="test-api-key",
    )

    response = create_openai_response()

    provider.client.images.generate = MagicMock(
        return_value=response,
    )

    request = create_request(tmp_path)

    provider.generate(request)

    provider.client.images.generate.assert_called_once_with(
        model="gpt-image-2",
        prompt=request.prompt,
        size="1536x864",
        quality="medium",
        n=1,
    )


def test_generate_creates_output_directory(
    tmp_path: Path,
) -> None:
    provider = OpenAIImageProvider(
        api_key="test-api-key",
    )

    response = create_openai_response()

    provider.client.images.generate = MagicMock(
        return_value=response,
    )

    output_directory = (
        tmp_path
        / "nested"
        / "images"
    )

    request = ImageGenerationRequest(
        image_id="scene_002",
        scene_id="scene_002",
        prompt="A stickman pirate.",
        provider="openai",
        output_directory=str(output_directory),
    )

    result = provider.generate(request)

    assert result.status == "completed"
    assert output_directory.exists()


def test_generate_handles_empty_response(
    tmp_path: Path,
) -> None:
    provider = OpenAIImageProvider(
        api_key="test-api-key",
    )

    response = MagicMock()
    response.data = []

    provider.client.images.generate = MagicMock(
        return_value=response,
    )

    request = create_request(tmp_path)

    result = provider.generate(request)

    assert result.status == "failed"
    assert result.file_path is None
    assert (
        result.error_message
        == "OpenAI returned no image data."
    )


def test_generate_handles_missing_base64(
    tmp_path: Path,
) -> None:
    provider = OpenAIImageProvider(
        api_key="test-api-key",
    )

    image_data = MagicMock()
    image_data.b64_json = None

    response = MagicMock()
    response.data = [image_data]

    provider.client.images.generate = MagicMock(
        return_value=response,
    )

    request = create_request(tmp_path)

    result = provider.generate(request)

    assert result.status == "failed"
    assert result.file_path is None
    assert (
        result.error_message
        == (
            "OpenAI response did not contain "
            "base64 image data."
        )
    )


def test_generate_handles_invalid_base64(
    tmp_path: Path,
) -> None:
    provider = OpenAIImageProvider(
        api_key="test-api-key",
    )

    image_data = MagicMock()
    image_data.b64_json = "not-valid-base64!"

    response = MagicMock()
    response.data = [image_data]

    provider.client.images.generate = MagicMock(
        return_value=response,
    )

    request = create_request(tmp_path)

    result = provider.generate(request)

    assert result.status == "failed"
    assert result.file_path is None
    assert (
        result.error_message
        == (
            "OpenAI returned invalid Base64 "
            "image data."
        )
    )


def test_generate_handles_api_exception(
    tmp_path: Path,
) -> None:
    provider = OpenAIImageProvider(
        api_key="test-api-key",
    )

    provider.client.images.generate = MagicMock(
        side_effect=RuntimeError(
            "API connection failed."
        ),
    )

    request = create_request(tmp_path)

    result = provider.generate(request)

    assert result.status == "failed"
    assert result.file_path is None
    assert (
        result.error_message
        == "API connection failed."
    )