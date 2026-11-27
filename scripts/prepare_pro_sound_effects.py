"""Validate and extract the Pro sound-effects release archive."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.video.pro_director import prepare_sound_effects_archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    directory = prepare_sound_effects_archive(
        arguments.archive,
        arguments.output,
    )
    print(f"Prepared Pro sound-effects library at {directory}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
