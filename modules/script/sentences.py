"""Deterministic sentence segmentation for narration text."""

import re

_TERMINAL_MARKS = ".!?…"
_CLOSING_MARKS = "\"'”’)]}»"
_TITLE_ABBREVIATIONS = {
    "capt",
    "dr",
    "jr",
    "mr",
    "mrs",
    "ms",
    "prof",
    "rev",
    "sr",
    "st",
}
_ABBREVIATIONS = {
    "a.m",
    "ave",
    "e.g",
    "etc",
    "i.e",
    "u.k",
    "u.s",
    "v",
    "vs",
}


def _is_nonterminal_period(text: str, index: int) -> bool:
    if (
        index > 0
        and index + 1 < len(text)
        and text[index - 1].isdigit()
        and text[index + 1].isdigit()
    ):
        return True

    prefix = text[:index]
    token_match = re.search(r"([A-Za-z]+(?:\.[A-Za-z]+)*)$", prefix)
    if token_match is None:
        return False

    token = token_match.group(1).casefold()
    if token in _TITLE_ABBREVIATIONS or token in {"u.k", "u.s"}:
        return True
    if token in _ABBREVIATIONS:
        following_word = re.match(r"\s+([A-Z])", text[index + 1 :])
        if following_word is None or not following_word.group(1).isupper():
            return True

    if len(token) == 1:
        following_text = text[index + 1 :]
        if re.match(r"(?:\s+[A-Z]\.)+\s+[A-Z][a-z]", following_text):
            return True
        if token != "i" and re.match(r"\s+[A-Z][a-z]", following_text):
            return True

    return False


def split_sentences(text: str) -> list[str]:
    """Split narration at sentence punctuation, preserving each sentence's text."""
    sentences: list[str] = []
    sentence_start = 0
    index = 0

    while index < len(text):
        if text[index] not in _TERMINAL_MARKS:
            index += 1
            continue
        if text[index] == "." and _is_nonterminal_period(text, index):
            index += 1
            continue

        punctuation_end = index + 1
        while (
            punctuation_end < len(text)
            and text[punctuation_end] in _TERMINAL_MARKS
        ):
            punctuation_end += 1
        while (
            punctuation_end < len(text)
            and text[punctuation_end] in _CLOSING_MARKS
        ):
            punctuation_end += 1

        if punctuation_end < len(text) and not text[punctuation_end].isspace():
            index = punctuation_end
            continue

        sentence = text[sentence_start:punctuation_end].strip()
        if sentence:
            sentences.append(sentence)
        index = punctuation_end
        while index < len(text) and text[index].isspace():
            index += 1
        sentence_start = index

    remainder = text[sentence_start:].strip()
    if remainder:
        sentences.append(remainder)
    return sentences
