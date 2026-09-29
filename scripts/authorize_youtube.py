"""Complete YouTube OAuth once and save the refreshable local token."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.publishing.youtube_provider import YouTubeProvider


load_dotenv(PROJECT_ROOT / ".env")


def main() -> int:
    credentials_file = os.getenv("GOOGLE_CLIENT_SECRETS_FILE")
    token_file = os.getenv("GOOGLE_TOKEN_FILE")
    if not credentials_file or not token_file:
        raise RuntimeError(
            "GOOGLE_CLIENT_SECRETS_FILE and GOOGLE_TOKEN_FILE must be configured in .env."
        )

    credentials_path = Path(credentials_file)
    token_path = Path(token_file)
    if not credentials_path.is_file():
        raise FileNotFoundError(f"Google client secrets file not found: {credentials_path}")

    print("Opening Google OAuth consent in your browser. No video upload will occur.")
    provider = YouTubeProvider(credentials_path, token_path)
    provider.service
    if not token_path.is_file():
        raise RuntimeError("OAuth completed but the token file was not created.")
    print("YouTube OAuth token saved successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
