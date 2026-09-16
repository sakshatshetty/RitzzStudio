import pytest
from pydantic import ValidationError

from modules.image.models import (
    ImageAsset,
    ImageGenerationRequest,
    ImageGenerationResult,
)


def test_image_asset_model():
    asset = ImageAsset(
        image_id="image_001",
        scene_id="scene_001",
        provider="openai",
        prompt="Simple stick-man pirate illustration.",
    )

    assert asset.image_id == "image_001"
    assert asset.scene_id == "scene_001"
    assert asset.provider == "openai"
    assert asset.status == "pending"
    assert asset.file_path is None


def test_image_generation_request():
    request = ImageGenerationRequest(
        image_id="image_001",
        scene_id="scene_001",
        prompt="Simple stick-man pirate illustration.",
        output_directory="output/images",
    )

    assert request.provider == "openai"
    assert request.width == 1024
    assert request.height == 1024


def test_image_generation_request_requires_prompt():
    with pytest.raises(ValidationError):
        ImageGenerationRequest(
            image_id="image_001",
            scene_id="scene_001",
            prompt="",
            output_directory="output/images",
        )


def test_image_generation_result_completed():
    result = ImageGenerationResult(
        image_id="image_001",
        scene_id="scene_001",
        provider="openai",
        status="completed",
        file_path="output/images/image_001.png",
    )

    assert result.status == "completed"
    assert result.file_path == (
        "output/images/image_001.png"
    )


def test_image_generation_result_failed():
    result = ImageGenerationResult(
        image_id="image_001",
        scene_id="scene_001",
        provider="openai",
        status="failed",
        error_message="Generation failed.",
    )

    assert result.status == "failed"
    assert result.error_message == (
        "Generation failed."
    )


def test_invalid_provider_fails():
    with pytest.raises(ValidationError):
        ImageAsset.model_validate(
            {
                "image_id": "image_001",
                "scene_id": "scene_001",
                "provider": "invalid",
                "prompt": "Test prompt",
            }
        )


def test_invalid_status_fails():
    with pytest.raises(ValidationError):
        ImageAsset.model_validate(
            {
                "image_id": "image_001",
                "scene_id": "scene_001",
                "provider": "openai",
                "prompt": "Test prompt",
                "status": "invalid",
            }
        )