from pathlib import Path

from modules.script.engine import ScriptEngine


PROJECT_ROOT = (
    Path("projects")
    / "20260820_001_why_do_pirates_wear_eye_patches"
)

RESEARCH_FILE = (
    PROJECT_ROOT
    / "research"
    / "research.json"
)

OUTLINE_FILE = (
    PROJECT_ROOT
    / "outline"
    / "outline.json"
)

SCRIPT_DIRECTORY = (
    PROJECT_ROOT
    / "script"
)


def main() -> None:
    print()
    print("=" * 60)
    print("RITZZ SCRIPT ENGINE")
    print("=" * 60)
    print()

    engine = ScriptEngine()

    script = engine.create_script(
        research_file=RESEARCH_FILE,
        outline_file=OUTLINE_FILE,
        script_directory=SCRIPT_DIRECTORY,
        force_refresh=True,
    )

    print()
    print("=" * 60)
    print("SCRIPT GENERATION COMPLETE")
    print("=" * 60)
    print()

    print(f"Topic: {script.topic}")
    print(
        f"Target duration: "
        f"{script.target_duration_seconds}s"
    )
    print(
        f"Estimated duration: "
        f"{script.total_estimated_seconds}s"
    )
    print(
        f"Word count: "
        f"{script.total_word_count}"
    )
    print(
        f"Sections: "
        f"{len(script.sections)}"
    )

    print()
    print("Sections:")

    for section in script.sections:
        print(
            f"{section.section_id} | "
            f"{section.title} | "
            f"{section.estimated_seconds}s | "
            f"{section.research_sources}"
        )

    print()
    print(
        f"Saved to: "
        f"{SCRIPT_DIRECTORY / 'script.json'}"
    )
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()