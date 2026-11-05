"""Validate required GitHub Actions secrets without exposing their values."""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.image.models import IMAGE_MODEL_OPTIONS

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


def validate_prerequisites(
    *,
    creative_package: bool = False,
    youtube_upload: bool = False,
    image_model: str | None = None,
    tts_provider: str = "elevenlabs",
) -> dict[str, str]:
    if creative_package and youtube_upload:
        raise ValueError(
            "Creative-package and YouTube-upload validation modes are mutually exclusive."
        )
    if tts_provider not in {"elevenlabs", "chatterbox"}:
        raise ValueError(
            "Unsupported narration provider; choose elevenlabs or chatterbox."
        )
    if youtube_upload:
        required_variables = (
            "GOOGLE_CLIENT_SECRETS_B64",
            "GOOGLE_TOKEN_B64",
        )
    elif creative_package:
        provider_variables = (
            ("ELEVENLABS_API_KEY", "RITZZ_VOICE_ID")
            if tts_provider == "elevenlabs"
            else ()
        )
        required_variables = (
            *provider_variables,
            "GOOGLE_CLIENT_SECRETS_B64",
            "GOOGLE_TOKEN_B64",
        )
    else:
        required_variables = REQUIRED_ENVIRONMENT_VARIABLES
    if image_model is not None and image_model not in IMAGE_MODEL_OPTIONS:
        raise ValueError(
            "Unsupported image model; choose one of: "
            + ", ".join(IMAGE_MODEL_OPTIONS)
        )
    if youtube_upload and image_model is not None:
        raise ValueError("Image-model validation is not applicable to YouTube uploads.")
    if image_model == "FLUX_SCHNELL":
        required_variables += ("REPLICATE_API_TOKEN",)
    missing = [
        name
        for name in required_variables
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise ValueError(f"Missing required pipeline secrets: {', '.join(missing)}")

    if creative_package and tts_provider == "chatterbox":
        conditionals_file = os.environ.get(
            "CHATTERBOX_VOICE_CONDITIONALS_FILE",
            "",
        ).strip()
        if not conditionals_file or not Path(conditionals_file).is_file():
            raise ValueError(
                "CHATTERBOX_VOICE_CONDITIONALS_FILE is missing or is not a file."
            )

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
    parser.add_argument(
        "--youtube-upload",
        action="store_true",
        help="Validate only YouTube OAuth credentials required for an upload.",
    )
    parser.add_argument(
        "--image-model",
        choices=IMAGE_MODEL_OPTIONS,
        help="Validate credentials for the selected creative-workflow image model.",
    )
    parser.add_argument(
        "--tts-provider",
        choices=("elevenlabs", "chatterbox"),
        default="elevenlabs",
        help="Validate credentials for the selected narration provider.",
    )
    arguments = parser.parse_args()
    result = validate_prerequisites(
        creative_package=arguments.creative_package,
        youtube_upload=arguments.youtube_upload,
        image_model=arguments.image_model,
        tts_provider=arguments.tts_provider,
    )
    print("Pipeline prerequisites passed.")
    for name, value in result.items():
        print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
