"""Validate required GitHub Actions secrets without exposing their values."""

import argparse
import base64
import json
import os
from typing import Any

REQUIRED_ENVIRONMENT_VARIABLES = (
    "OPENAI_API_KEY",
    "VIDIQ_MCP_API_KEY",
    "ELEVENLABS_API_KEY",
    "RITZZ_VOICE_ID",
    "GOOGLE_CLIENT_SECRETS_B64",
    "GOOGLE_TOKEN_B64",
)


def _decode_json_secret(name: str) -> dict[str, Any]:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is missing.")
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not valid Base64-encoded JSON.") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{name} must decode to a JSON object.")
    return payload


def validate_prerequisites(*, creative_package: bool = False) -> dict[str, str]:
    required_variables = (
        tuple(
            name
            for name in REQUIRED_ENVIRONMENT_VARIABLES
            if name != "VIDIQ_MCP_API_KEY"
        )
        if creative_package
        else REQUIRED_ENVIRONMENT_VARIABLES
    )
    missing = [
        name
        for name in required_variables
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise ValueError(f"Missing required pipeline secrets: {', '.join(missing)}")

    client_payload = _decode_json_secret("GOOGLE_CLIENT_SECRETS_B64")
    client_config = client_payload.get("installed") or client_payload.get("web")
    if not isinstance(client_config, dict) or not client_config.get("client_id") or not client_config.get("client_secret"):
        raise ValueError("GOOGLE_CLIENT_SECRETS_B64 does not contain an OAuth client configuration.")

    token_payload = _decode_json_secret("GOOGLE_TOKEN_B64")
    if not token_payload.get("refresh_token") and not token_payload.get("token"):
        raise ValueError("GOOGLE_TOKEN_B64 does not contain an OAuth token.")

    return {
        "required_secrets": str(len(required_variables)),
        "oauth_client_json": "valid",
        "oauth_token_json": "valid",
        "api_calls_made": "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--creative-package",
        action="store_true",
        help="Validate the creative ZIP workflow's credentials instead of vidIQ.",
    )
    arguments = parser.parse_args()
    result = validate_prerequisites(creative_package=arguments.creative_package)
    print("Pipeline prerequisites passed.")
    for name, value in result.items():
        print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
