import base64
import json

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
