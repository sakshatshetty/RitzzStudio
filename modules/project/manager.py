import json
import re
from datetime import datetime
from pathlib import Path

from .models import Project


class ProjectManager:
    """Creates and manages Ritzz Studio video projects."""

    PROJECT_DIRECTORIES = [
        "research",
        "outline",
        "script",
        "storyboard",
        "images",
        "audio",
        "video",
        "thumbnail",
        "exports",
        "logs",
    ]

    def __init__(self, projects_dir: Path):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def create_slug(title: str) -> str:
        """Convert a video title into a filesystem-safe slug."""
        slug = title.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"[\s-]+", "_", slug)
        return slug.strip("_")

    def _next_project_id(self) -> str:
        """Generate the next sequential project ID for today."""
        today = datetime.now().strftime("%Y%m%d")

        existing_projects = list(self.projects_dir.glob(f"{today}_*"))

        sequence = len(existing_projects) + 1

        return f"{today}_{sequence:03d}"

    def create_project(self, title: str) -> Project:
        """Create a new project and its directory structure."""

        title = title.strip()

        if not title:
            raise ValueError("Project title cannot be empty.")

        project_id = self._next_project_id()
        slug = self.create_slug(title)

        if not slug:
            raise ValueError("Project title must contain letters or numbers.")

        project_name = f"{project_id}_{slug}"
        project_path = self.projects_dir / project_name

        project_path.mkdir(parents=True, exist_ok=False)

        for directory in self.PROJECT_DIRECTORIES:
            (project_path / directory).mkdir()

        project = Project(
            project_id=project_id,
            title=title,
            slug=slug,
        )

        self._save_project(project, project_path)

        return project

    def get_project_path(self, project: Project) -> Path:
        """Return the filesystem path for a project."""
        return self.projects_dir / f"{project.project_id}_{project.slug}"

    def load_project(self, project_id: str) -> Project:
        """Load an existing project from project.json."""

        project_path = self._find_project_path(project_id)
        project_file = project_path / "project.json"

        if not project_file.exists():
            raise FileNotFoundError(
                f"project.json not found for project: {project_id}"
            )

        with project_file.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return Project.from_dict(data)

    def update_status(self, project_id: str, status: str) -> Project:
        """Update the current project status."""

        project = self.load_project(project_id)
        project.status = status

        self._save_project(
            project,
            self.get_project_path(project),
        )

        return project

    def complete_step(self, project_id: str, step: str) -> Project:
        """Mark a pipeline step as completed."""

        project = self.load_project(project_id)

        if step not in project.steps:
            raise ValueError(f"Unknown project step: {step}")

        project.steps[step] = True
        project.status = f"{step}_completed"

        self._save_project(
            project,
            self.get_project_path(project),
        )

        return project

    def _find_project_path(self, project_id: str) -> Path:
        """Find a project directory using its project ID."""

        matches = list(
            self.projects_dir.glob(f"{project_id}_*")
        )

        if not matches:
            raise FileNotFoundError(
                f"Project not found: {project_id}"
            )

        if len(matches) > 1:
            raise RuntimeError(
                f"Multiple projects found for ID: {project_id}"
            )

        return matches[0]

    @staticmethod
    def _save_project(
        project: Project,
        project_path: Path,
    ) -> None:
        """Save project metadata to project.json."""

        project_file = project_path / "project.json"

        with project_file.open("w", encoding="utf-8") as file:
            json.dump(
                project.to_dict(),
                file,
                indent=4,
                ensure_ascii=False,
            )