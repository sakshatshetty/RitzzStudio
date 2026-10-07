"""Download one creative ZIP from the configured private HTTPS asset host."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.creative_package import CREATIVE_PACKAGE_MAX_ARCHIVE_BYTES


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise RuntimeError("Creative package download redirects are not permitted.")


def _validate_url(url: str, allowed_host: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.casefold() != allowed_host.casefold()
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise ValueError(
            "Creative package URL must be HTTPS on the configured asset host, "
            "without credentials, query parameters, or fragments."
        )


def download_creative_package(
    url: str,
    allowed_host: str,
    token: str,
    destination: str | Path,
) -> Path:
    if not allowed_host.strip() or not token.strip():
        raise ValueError(
            "RITZZ_CREATIVE_PACKAGE_HOST and "
            "RITZZ_CREATIVE_PACKAGE_DOWNLOAD_TOKEN are required."
        )
    _validate_url(url, allowed_host.strip())
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    opener = build_opener(_RejectRedirects())
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/zip, application/octet-stream",
        },
    )
    try:
        with opener.open(request, timeout=60) as response:
            if response.getcode() != 200:
                raise RuntimeError(
                    f"Creative package host returned HTTP {response.getcode()}."
                )
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > CREATIVE_PACKAGE_MAX_ARCHIVE_BYTES:
                raise ValueError("Creative package ZIP exceeds the 250 MiB limit.")
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > CREATIVE_PACKAGE_MAX_ARCHIVE_BYTES:
                        raise ValueError(
                            "Creative package ZIP exceeds the 250 MiB limit."
                        )
                    temporary.write(block)
        temporary_path.replace(target)
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        if "temporary_path" in locals():
            temporary_path.unlink(missing_ok=True)
        raise RuntimeError(f"Creative package download failed: {exc}") from exc
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("RITZZ_CREATIVE_PACKAGE_URL"),
        required=os.environ.get("RITZZ_CREATIVE_PACKAGE_URL") is None,
    )
    parser.add_argument(
        "--output",
        default=".pipeline-artifacts/creative-package.zip",
    )
    arguments = parser.parse_args()
    path = download_creative_package(
        arguments.url,
        os.environ.get("RITZZ_CREATIVE_PACKAGE_HOST", ""),
        os.environ.get("RITZZ_CREATIVE_PACKAGE_DOWNLOAD_TOKEN", ""),
        arguments.output,
    )
    print(f"Creative package downloaded to {path}; URL and credentials were not logged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
