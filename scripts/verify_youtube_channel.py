"""Verify that the configured YouTube OAuth token selects the requested channel."""

import os
import sys
from pathlib import Path

from google.auth.exceptions import RefreshError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.publishing.youtube_provider import YouTubeProvider


def main() -> int:
    expected_title = os.environ.get("RITZZ_YOUTUBE_CHANNEL_TITLE", "").strip()
    if not expected_title:
        raise ValueError("RITZZ_YOUTUBE_CHANNEL_TITLE is required.")

    credentials_file = Path(os.environ["GOOGLE_CLIENT_SECRETS_FILE"])
    token_file = Path(os.environ["GOOGLE_TOKEN_FILE"])
    try:
        channel = YouTubeProvider(
            credentials_file,
            token_file,
        ).verify_authenticated_channel(expected_title)
    except RefreshError:
        token_secret_by_channel = {
            "Ritzz-Explains": "GOOGLE_TOKEN_B64",
            "RitzzHistory": "GOOGLE_TOKEN_RITZZ_HISTORY_B64",
            "RitzzTech1": "GOOGLE_TOKEN_RITZZ_TECH_B64",
        }
        token_secret_by_title = {
            "ritzz": "GOOGLE_TOKEN_B64",
            "ritzz history": "GOOGLE_TOKEN_RITZZ_HISTORY_B64",
            "ritzz tech": "GOOGLE_TOKEN_RITZZ_TECH_B64",
        }
        selected_channel = os.environ.get("RITZZ_YOUTUBE_CHANNEL", "").strip()
        token_secret = token_secret_by_channel.get(
            selected_channel,
            token_secret_by_title.get(expected_title.casefold()),
        )
        secret_instruction = (
            f"Replace the GitHub Actions secret `{token_secret}`."
            if token_secret
            else "Replace the GitHub Actions OAuth token secret configured for this channel."
        )
        print(
            "ERROR: Google rejected the saved YouTube OAuth refresh token "
            "(invalid_grant; the token is expired or revoked).",
            file=sys.stderr,
        )
        print(
            f"Reauthorize '{expected_title}' with scripts/authorize_youtube.py, "
            "verify it with scripts/verify_youtube_channel.py, and Base64-encode "
            f"the new token JSON. {secret_instruction}",
            file=sys.stderr,
        )
        return 1

    print(
        "Selected YouTube channel verified: "
        f"{channel['channel_title']} ({channel['channel_id']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
