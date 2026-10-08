from modules.script.sentences import split_sentences


def test_splits_common_sentence_endings_and_preserves_punctuation():
    assert split_sentences('He asked, "Why?" She answered!') == [
        'He asked, "Why?"',
        "She answered!",
    ]


def test_does_not_split_decimals_titles_initials_or_abbreviations():
    assert split_sentences(
        "Dr. Jane Smith measured 3.14 units. J. R. R. Tolkien wrote."
    ) == [
        "Dr. Jane Smith measured 3.14 units.",
        "J. R. R. Tolkien wrote.",
    ]


def test_keeps_unpunctuated_remainder_as_one_sentence():
    assert split_sentences("The final narration line has no period") == [
        "The final narration line has no period"
    ]


def test_handles_ellipsis_and_consecutive_terminal_marks():
    assert split_sentences("Wait… What?! Go.") == [
        "Wait…",
        "What?!",
        "Go.",
    ]
