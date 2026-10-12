"""Verify that the configured YouTube OAuth token selects the requested channel."""

import os
import sys
from pathlib import Path

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
    channel = YouTubeProvider(
        credentials_file,
        token_file,
    ).verify_authenticated_channel(expected_title)
    print(
        "Selected YouTube channel verified: "
        f"{channel['channel_title']} ({channel['channel_id']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
