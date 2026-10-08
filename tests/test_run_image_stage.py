import pytest

from modules.image.providers.mock import MockImageProvider
from scripts import run_image_stage


def test_flux_schnell_is_the_default_image_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MockImageProvider()
    monkeypatch.delenv("RITZZ_IMAGE_MODEL", raising=False)
    monkeypatch.setattr(
        run_image_stage,
        "ReplicateFluxSchnellProvider",
        lambda: provider,
    )

    engine = run_image_stage._create_image_engine()

    assert engine.provider is provider
    assert engine.provider_name == "replicate"


def test_gpt_image_backend_remains_selectable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MockImageProvider()
    monkeypatch.setattr(
        run_image_stage,
        "OpenAIImageProvider",
        lambda: provider,
    )

    engine = run_image_stage._create_image_engine("GPT_IMAGE_2")

    assert engine.provider is provider
    assert engine.provider_name == "openai"


def test_image_stage_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported RITZZ_IMAGE_MODEL"):
        run_image_stage._create_image_engine("UNKNOWN")
