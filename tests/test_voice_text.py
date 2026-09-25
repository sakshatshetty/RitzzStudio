from modules.voice.text import ensure_terminal_punctuation


def test_adds_sentence_stop_when_missing():
    assert ensure_terminal_punctuation("A calm explanation") == "A calm explanation."


def test_preserves_existing_terminal_punctuation():
    assert ensure_terminal_punctuation("Is that true?") == "Is that true?"
    assert ensure_terminal_punctuation("A clear answer!") == "A clear answer!"


def test_normalizes_spacing_without_changing_words():
    assert ensure_terminal_punctuation("  A   calm   voice  ") == "A calm voice."


def test_repairs_dangling_clause_mark_before_quote():
    assert ensure_terminal_punctuation('He said, “Wait,”') == 'He said, “Wait.”'
