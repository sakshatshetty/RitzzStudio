from io import BytesIO
from pathlib import Path
from urllib.request import Request

import pytest

from scripts import download_creative_package


@pytest.mark.parametrize(
    "url",
    [
        "http://assets.example.com/creative.zip",
        "https://other.example.com/creative.zip",
        "https://assets.example.com/creative.zip?token=embedded",
        "https://user:password@assets.example.com/creative.zip",
    ],
)
def test_rejects_untrusted_or_credential_bearing_package_urls(url):
    with pytest.raises(ValueError, match="configured asset host"):
        download_creative_package._validate_url(
            url,
            "assets.example.com",
        )


def test_download_sends_repository_secret_only_to_allowlisted_https_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    payload = b"private creative package bytes"

    class Response(BytesIO):
        def __init__(self, contents: bytes):
            super().__init__(contents)
            self.headers = {}

        def getcode(self):
            return 200

    class Opener:
        def open(self, request: Request, timeout: int):
            assert request.full_url == "https://assets.example.com/packages/pilot.zip"
            assert request.get_header("Authorization") == "Bearer private-token"
            assert timeout == 60
            return Response(payload)

    monkeypatch.setattr(
        download_creative_package,
        "build_opener",
        lambda *_handlers: Opener(),
    )
    destination = tmp_path / "creative.zip"

    result = download_creative_package.download_creative_package(
        "https://assets.example.com/packages/pilot.zip",
        "assets.example.com",
        "private-token",
        destination,
    )

    assert result == destination
    assert destination.read_bytes() == payload
