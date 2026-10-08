import subprocess
from pathlib import Path

import pytest

from scripts import download_creative_package


def test_downloads_named_asset_from_github_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GH_TOKEN", "github-token")

    def fake_run(arguments, **_kwargs):
        assert arguments[:4] == [
            "gh",
            "release",
            "download",
            "pilot-v1",
        ]
        assert arguments[arguments.index("--repo") + 1] == "sakshatshetty/RitzzStudio"
        assert arguments[arguments.index("--pattern") + 1] == "creative-package.zip"
        output_directory = Path(arguments[arguments.index("--dir") + 1])
        output_directory.joinpath("creative-package.zip").write_bytes(b"zip bytes")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(download_creative_package.subprocess, "run", fake_run)

    result = download_creative_package.download_creative_package(
        "pilot-v1",
        "sakshatshetty/RitzzStudio",
        tmp_path / "creative-package.zip",
    )

    assert result.read_bytes() == b"zip bytes"


@pytest.mark.parametrize(
    ("release_tag", "repository", "error"),
    [
        ("--help", "sakshatshetty/RitzzStudio", "Release tag"),
        ("pilot", "invalid repo", "GITHUB_REPOSITORY"),
    ],
)
def test_rejects_invalid_release_coordinates(
    release_tag: str,
    repository: str,
    error: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GH_TOKEN", "github-token")

    with pytest.raises(ValueError, match=error):
        download_creative_package.download_creative_package(
            release_tag,
            repository,
            tmp_path / "creative-package.zip",
        )


def test_requires_github_token_for_private_release_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with pytest.raises(ValueError, match="GH_TOKEN is required"):
        download_creative_package.download_creative_package(
            "pilot-v1",
            "sakshatshetty/RitzzStudio",
            tmp_path / "creative-package.zip",
        )


def test_rejects_oversized_release_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GH_TOKEN", "github-token")

    def fake_run(arguments, **_kwargs):
        output_directory = Path(arguments[arguments.index("--dir") + 1])
        downloaded = output_directory / "creative-package.zip"
        with downloaded.open("wb") as package:
            package.truncate(
                download_creative_package.CREATIVE_PACKAGE_MAX_ARCHIVE_BYTES + 1
            )
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(download_creative_package.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="250 MiB limit"):
        download_creative_package.download_creative_package(
            "pilot-v1",
            "sakshatshetty/RitzzStudio",
            tmp_path / "creative-package.zip",
        )
