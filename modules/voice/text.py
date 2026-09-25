"""Small, deterministic text preparation for speech synthesis."""

import re


_TERMINAL_MARKS = ".!?…"
_CLOSING_MARKS = "\"'”’)]}»"


def ensure_terminal_punctuation(text: str) -> str:
    """Trim narration and ensure it ends with a spoken sentence mark."""

    prepared = re.sub(r"[ \t]+", " ", text).strip()
    if not prepared:
        return prepared

    index = len(prepared) - 1
    while index >= 0 and prepared[index] in _CLOSING_MARKS:
        index -= 1

    if index >= 0 and prepared[index] in _TERMINAL_MARKS:
        return prepared

    # A dangling clause separator is not a suitable end for a complete
    # narration section. Replace it with a full stop before closing quotes.
    if index >= 0 and prepared[index] in ",;:—–-":
        prepared = prepared[:index] + "." + prepared[index + 1 :]
    else:
        prepared += "."

    return prepared
