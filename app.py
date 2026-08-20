from pathlib import Path

from modules.project import ProjectManager


PROJECT_ROOT = Path(__file__).resolve().parent
PROJECTS_DIR = PROJECT_ROOT / "projects"


def main() -> None:
    print("=" * 50)
    print("              RITZZ STUDIO")
    print("=" * 50)
    print()

    title = input("Enter video topic:\n> ").strip()

    if not title:
        print("\n❌ Topic cannot be empty.")
        return

    manager = ProjectManager(PROJECTS_DIR)

    try:
        project = manager.create_project(title)

    except ValueError as exc:
        print(f"\n❌ {exc}")
        return

    project_path = manager.get_project_path(project)

    print()
    print("✅ Project created!")
    print()
    print(f"Project ID : {project.project_id}")
    print(f"Title      : {project.title}")
    print(f"Location   : {project_path}")
    print()
    print("Status     : created")
    print()
    print("=" * 50)


if __name__ == "__main__":
    main()