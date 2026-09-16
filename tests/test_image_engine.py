from pathlib import Path

import pytest

from modules.image.engine import ImageEngine
from modules.image.models import ImageAsset
from modules.image.providers.mock import MockImageProvider


def test_create_request(tmp_path: Path) -> None:
    provider = MockImageProvider()
    engine = ImageEngine(provider)

    request = engine.create_request(
        image_id="image_001",
        scene_id="scene_001",
        prompt="A pirate standing on a wooden ship.",
        output_directory=tmp_path,
    )

    assert request.image_id == "image_001"
    assert request.scene_id == "scene_001"
    assert request.prompt == (
        "A pirate standing on a wooden ship."
    )
    assert request.output_directory == str(tmp_path)
    assert request.provider == "openai"


def test_generate_with_mock_provider(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    engine = ImageEngine(provider)

    request = engine.create_request(
        image_id="image_001",
        scene_id="scene_001",
        prompt="A pirate standing on a ship.",
        output_directory=tmp_path,
    )

    result = engine.generate(request)

    assert result.status == "completed"
    assert result.image_id == "image_001"
    assert result.scene_id == "scene_001"
    assert result.file_path is not None

    assert Path(result.file_path).exists()

    assert len(provider.calls) == 1


def test_generate_asset_success(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    engine = ImageEngine(provider)

    request = engine.create_request(
        image_id="image_001",
        scene_id="scene_001",
        prompt="A pirate wearing an eye patch.",
        output_directory=tmp_path,
    )

    asset = engine.generate_asset(request)

    assert isinstance(asset, ImageAsset)
    assert asset.image_id == "image_001"
    assert asset.scene_id == "scene_001"
    assert asset.prompt == (
        "A pirate wearing an eye patch."
    )
    assert asset.provider == "openai"
    assert asset.status == "completed"
    assert asset.file_path is not None

    assert Path(asset.file_path).exists()


def test_generate_asset_failure(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider(
        fail_scene_id="scene_002"
    )
    engine = ImageEngine(provider)

    request = engine.create_request(
        image_id="image_002",
        scene_id="scene_002",
        prompt="A pirate ship at sunset.",
        output_directory=tmp_path,
    )

    asset = engine.generate_asset(request)

    assert asset.image_id == "image_002"
    assert asset.scene_id == "scene_002"
    assert asset.status == "failed"
    assert asset.file_path is None
    assert asset.error_message == (
        "Mock generation failure."
    )


def test_save_and_load_asset(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    engine = ImageEngine(provider)

    request = engine.create_request(
        image_id="image_001",
        scene_id="scene_001",
        prompt="A pirate on a ship.",
        output_directory=tmp_path / "images",
    )

    asset = engine.generate_asset(request)

    result_file = tmp_path / "asset.json"

    engine.save_asset(
        asset,
        result_file,
    )

    assert result_file.exists()

    loaded = engine.load_asset(result_file)

    assert loaded == asset


def test_load_missing_asset_raises(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    engine = ImageEngine(provider)

    missing_file = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError):
        engine.load_asset(missing_file)


def test_build_output_filename() -> None:
    assert (
        ImageEngine.build_output_filename(
            "image_001"
        )
        == "image_001.png"
    )


def test_provider_receives_request(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    engine = ImageEngine(provider)

    request = engine.create_request(
        image_id="image_005",
        scene_id="scene_005",
        prompt="A mysterious pirate cave.",
        output_directory=tmp_path,
    )

    engine.generate(request)

    assert len(provider.calls) == 1

    received_request = provider.calls[0]

    assert received_request.image_id == "image_005"
    assert received_request.scene_id == "scene_005"
    assert received_request.prompt == (
        "A mysterious pirate cave."
    )


def test_multiple_images_are_generated(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    engine = ImageEngine(provider)

    requests = [
        engine.create_request(
            image_id="image_001",
            scene_id="scene_001",
            prompt="Pirate on a ship.",
            output_directory=tmp_path,
        ),
        engine.create_request(
            image_id="image_002",
            scene_id="scene_002",
            prompt="Pirate looking at the horizon.",
            output_directory=tmp_path,
        ),
        engine.create_request(
            image_id="image_003",
            scene_id="scene_003",
            prompt="Pirate walking on deck.",
            output_directory=tmp_path,
        ),
    ]

    results = [
        engine.generate(request)
        for request in requests
    ]

    assert len(results) == 3
    assert len(provider.calls) == 3

    for index, result in enumerate(results, start=1):
        assert result.status == "completed"
        assert result.image_id == (
            f"image_{index:03d}"
        )
        assert result.scene_id == (
            f"scene_{index:03d}"
        )
        assert result.file_path is not None
        assert Path(result.file_path).exists()