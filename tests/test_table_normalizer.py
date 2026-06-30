from finix_restore.table_normalizer import TableNormalizer


def test_normalize_fullwidth_punctuation_in_cells():
    html = "<table><tr><td>（性别：男）</td><td>50 ％</td></tr></table>"

    result = TableNormalizer().normalize(html)

    assert "(性别:男)" in result
    assert "50%" in result


def test_normalize_paren_negative_and_trailing_zero():
    html = "<table><tr><td>(123.0)</td><td>100.00</td></tr></table>"

    result = TableNormalizer().normalize(html)

    assert "-123" in result
    assert "<td>100</td>" in result


def test_normalize_thousand_separator():
    html = "<table><tr><td>1,234,567</td></tr></table>"

    result = TableNormalizer().normalize(html)

    assert "1234567" in result


def test_normalize_skips_non_table_text():
    html = "正文（保留全角）\n<table><tr><td>（半角）</td></tr></table>"

    result = TableNormalizer().normalize(html)

    # 表外文本保持原样
    assert "正文（保留全角）" in result
    # 表内单元格被归一化
    assert "(半角)" in result


def test_normalize_no_table_returns_input():
    text = "纯文本（无表格）"

    assert TableNormalizer().normalize(text) == text
