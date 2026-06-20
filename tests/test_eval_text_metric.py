from finix_restore.eval.text_metric import normalize_text, text_edit


def test_normalize_text_collapses_whitespace_and_newlines():
    assert normalize_text("  a\r\nb \t c \n") == "a\nb c"


def test_text_edit_identical():
    assert text_edit("abc", "abc") == 0.0


def test_text_edit_single_substitution():
    assert text_edit("abcd", "abxd") == 0.25


def test_text_edit_empty_gt():
    assert text_edit("a", "") == 1.0
