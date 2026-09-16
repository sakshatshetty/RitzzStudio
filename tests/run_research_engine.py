from pathlib import Path

from modules.research.engine import ResearchEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent

RESEARCH_DIR = (
    PROJECT_ROOT
    / "projects"
    / "20260820_001_why_do_pirates_wear_eye_patches"
    / "research"
)


def main() -> None:
    engine = ResearchEngine()

    research = engine.research(
        topic="Why Do Pirates Wear Eye Patches?",
        research_directory=RESEARCH_DIR,
    )

    print()
    print("=" * 60)
    print("RITZZ RESEARCH COMPLETE")
    print("=" * 60)
    print()
    print(f"Topic: {research.topic}")
    print(f"Category: {research.category}")
    print()
    print("Key facts:", len(research.key_facts))
    print("Historical context:", len(research.historical_context))
    print("Myths:", len(research.common_myths))
    print("Surprising facts:", len(research.surprising_facts))
    print("Story angles:", len(research.possible_story_angles))
    print("Sources:", len(research.sources))
    print()
    print(f"Saved to: {RESEARCH_DIR / 'research.json'}")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()