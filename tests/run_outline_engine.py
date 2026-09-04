from pathlib import Path

from modules.outline.engine import OutlineEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROJECT_DIR = (
    PROJECT_ROOT
    / "projects"
    / "20260820_001_why_do_pirates_wear_eye_patches"
)

RESEARCH_FILE = PROJECT_DIR / "research" / "research.json"
OUTLINE_DIR = PROJECT_DIR / "outline"


def main() -> None:
    engine = OutlineEngine()

    outline = engine.create_outline(
        research_file=RESEARCH_FILE,
        outline_directory=OUTLINE_DIR,
    )

    print()
    print("=" * 60)
    print("RITZZ OUTLINE COMPLETE")
    print("=" * 60)
    print()
    print(f"Topic: {outline.topic}")
    print(f"Target duration: {outline.target_duration_seconds}s")
    print(
        f"Estimated duration: "
        f"{outline.total_estimated_seconds}s"
    )
    print()
    print(f"Hook: {outline.hook}")
    print()
    print(f"Sections: {len(outline.sections)}")
    print()

    for section in outline.sections:
        print(
            f"{section.section_id} | "
            f"{section.section_type} | "
            f"{section.title} | "
            f"{section.estimated_seconds}s"
        )

    print()
    print(f"Saved to: {OUTLINE_DIR / 'outline.json'}")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()