import base64
import json
from pathlib import Path

import pytest

from scripts.validate_pipeline_prerequisites import (
    REQUIRED_ENVIRONMENT_VARIABLES,
    validate_prerequisites,
)


def _encoded(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _set_valid_environment(monkeypatch):
    for name in REQUIRED_ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(name, "configured")
    monkeypatch.setenv(
        "GOOGLE_CLIENT_SECRETS_B64",
        _encoded({"installed": {"client_id": "client", "client_secret": "secret"}}),
    )
    monkeypatch.setenv(
        "GOOGLE_TOKEN_B64",
        _encoded({"refresh_token": "refresh"}),
    )


def test_validate_prerequisites_accepts_configured_secrets(monkeypatch):
    _set_valid_environment(monkeypatch)

    result = validate_prerequisites()

    assert result["oauth_client_json"] == "valid"
    assert result["oauth_token_json"] == "valid"
    assert result["api_calls_made"] == "none"


def test_creative_package_preflight_does_not_require_vidiq(monkeypatch):
    _set_valid_environment(monkeypatch)
    monkeypatch.delenv("VIDIQ_MCP_API_KEY")

    result = validate_prerequisites(creative_package=True)

    assert result["required_secrets"] == "5"
    assert result["api_calls_made"] == "none"


def test_flux_image_model_requires_replicate_token(monkeypatch):
    _set_valid_environment(monkeypatch)
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)

    with pytest.raises(ValueError, match="REPLICATE_API_TOKEN"):
        validate_prerequisites(
            creative_package=True,
            image_model="FLUX_SCHNELL",
        )

    monkeypatch.setenv("REPLICATE_API_TOKEN", "configured")
    result = validate_prerequisites(
        creative_package=True,
        image_model="FLUX_SCHNELL",
    )
    assert result["required_secrets"] == "6"


def test_gpt_image_model_does_not_require_replicate_token(monkeypatch):
    _set_valid_environment(monkeypatch)
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)

    result = validate_prerequisites(
        creative_package=True,
        image_model="GPT_IMAGE_2",
    )

    assert result["required_secrets"] == "5"


def test_validate_prerequisites_rejects_unknown_image_model(monkeypatch):
    _set_valid_environment(monkeypatch)

    with pytest.raises(ValueError, match="Unsupported image model"):
        validate_prerequisites(
            creative_package=True,
            image_model="UNKNOWN",
        )


def test_storyboard_generation_job_receives_openai_secret():
    workflow = Path(".github/workflows/ritzz-pipeline.yml").read_text(
        encoding="utf-8"
    )
    job = workflow.split("  storyboard-generation:", 1)[1].split(
        "\n  image-generation:", 1
    )[0]

    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in job


def test_image_generation_archives_and_restores_partial_scene_progress():
    workflow = Path(".github/workflows/ritzz-pipeline.yml").read_text(
        encoding="utf-8"
    )
    job = workflow.split("  image-generation:", 1)[1].split(
        "\n  render-video:", 1
    )[0]

    assert "name: Download partial image checkpoint" in job
    assert "resume_from_index == '5'" in job
    assert "endsWith(needs.restore-production.outputs.source_artifact, '-image_generation')" in job
    assert "name: Extract partial image checkpoint" in job
    assert "name: Download storyboard project" in job
    assert "if: always()" in job
    assert "fail --stage image_generation --artifacts image-project.tar.gz" in job
    assert "name: Upload image artifacts\n        if: always()" in job


def test_validate_prerequisites_reports_missing_secret(monkeypatch):
    _set_valid_environment(monkeypatch)
    monkeypatch.delenv("ELEVENLABS_API_KEY")

    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        validate_prerequisites()


def test_validate_prerequisites_rejects_invalid_google_token(monkeypatch):
    _set_valid_environment(monkeypatch)
    monkeypatch.setenv("GOOGLE_TOKEN_B64", _encoded({"access_token": "access-only"}))

    with pytest.raises(ValueError, match="OAuth token"):
        validate_prerequisites()
