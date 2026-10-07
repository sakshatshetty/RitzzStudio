"""Validate and import a user-supplied RITZZ creative package ZIP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import PROJECTS_DIR
from modules.project.creative_package import (
    CREATIVE_PACKAGE_WORKFLOW_VERSION,
    load_creative_package,
    materialize_creative_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--zip",
        dest="zip_path",
        default=os.environ.get("RITZZ_CREATIVE_PACKAGE_ZIP"),
        required=os.environ.get("RITZZ_CREATIVE_PACKAGE_ZIP") is None,
        help="Path to the approved creative-package ZIP.",
    )
    parser.add_argument(
        "--projects-dir",
        default=os.environ.get("RITZZ_PROJECTS_DIR", str(PROJECTS_DIR)),
    )
    arguments = parser.parse_args()

    package = load_creative_package(arguments.zip_path)
    project, project_directory = materialize_creative_package(
        package,
        arguments.projects_dir,
    )
    print(
        json.dumps(
            {
                "workflow_version": CREATIVE_PACKAGE_WORKFLOW_VERSION,
                "project_id": project.project_id,
                "topic": package.manifest.topic,
                "target_duration_seconds": package.target_duration_seconds,
                "project_directory": str(project_directory),
                "archive_sha256": package.archive_sha256,
                "input_validation": "PASS",
                "creative_assets_are_immutable": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
