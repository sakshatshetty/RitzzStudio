"""Download one creative ZIP attached to a GitHub release."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.creative_package import CREATIVE_PACKAGE_MAX_ARCHIVE_BYTES

CREATIVE_PACKAGE_ASSET = "creative-package.zip"


def download_creative_package(
    release_tag: str,
    repository: str,
    destination: str | Path,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", release_tag):
        raise ValueError("Release tag contains unsupported characters.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GITHUB_REPOSITORY must be in owner/repository format.")
    if not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"):
        raise ValueError("GH_TOKEN is required to download a private release asset.")

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=target.parent,
        prefix=f".{target.name}.",
    ) as temporary_directory:
        temporary_path = Path(temporary_directory)
        result = subprocess.run(
            [
                "gh",
                "release",
                "download",
                release_tag,
                "--repo",
                repository,
                "--pattern",
                CREATIVE_PACKAGE_ASSET,
                "--dir",
                str(temporary_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode:
            details = result.stderr.strip() or "GitHub CLI returned an error."
            raise RuntimeError(
                f"Could not download {CREATIVE_PACKAGE_ASSET} from release "
                f"{release_tag}: {details}"
            )

        downloaded = temporary_path / CREATIVE_PACKAGE_ASSET
        if not downloaded.is_file():
            raise RuntimeError(
                f"Release {release_tag} does not contain "
                f"{CREATIVE_PACKAGE_ASSET}."
            )
        if downloaded.stat().st_size > CREATIVE_PACKAGE_MAX_ARCHIVE_BYTES:
            raise ValueError("Creative package ZIP exceeds the 250 MiB limit.")
        downloaded.replace(target)

    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
    )
    parser.add_argument(
        "--output",
        default=".pipeline-artifacts/creative-package.zip",
    )
    arguments = parser.parse_args()
    path = download_creative_package(
        arguments.release_tag,
        arguments.repository,
        arguments.output,
    )
    print(
        f"Creative package downloaded from release {arguments.release_tag} "
        f"to {path}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
