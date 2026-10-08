"""Research visual context for a user-supplied creative package."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.config import ProductionConfig
from modules.project.manager import ProjectManager
from modules.research.engine import ResearchEngine


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    project_manager = ProjectManager(Path("projects"))
    project = project_manager.load_project(project_id)
    project_directory = project_manager.get_project_path(project)
    config = ProductionConfig.model_validate_json(
        (project_directory / "production_config.json").read_text(
            encoding="utf-8"
        )
    )
    research = ResearchEngine().research(
        project.title,
        project_directory / "research",
        production_config=config,
        force_refresh=os.environ.get("RITZZ_FORCE_RESEARCH") == "true",
    )
    if research.topic != project.title:
        raise ValueError(
            "Visual-context research returned a topic that does not match "
            "the user-supplied project topic."
        )
    print(
        f"Visual-context research saved for supplied topic "
        f"{project.title!r}: {len(research.sources)} sources."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
