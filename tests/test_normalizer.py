from finix_restore.normalizer import MarkdownNormalizer


def test_normalizer_fixes_heading_spacing_and_trailing_spaces():
    raw = "##1.1 保险责任   \r\n正文   \n###2.1.1 赔付  "

    normalized = MarkdownNormalizer().normalize(raw)

    assert normalized == "## 1.1 保险责任\n正文\n### 2.1.1 赔付\n"


def test_normalizer_preserves_financial_numbers_and_terms():
    raw = "赔付比例为80%，金额1,000.50元。\n备案号：C00000232522022021915133\n##1.2 主险与附加险关系"

    normalized = MarkdownNormalizer().normalize(raw)

    assert "80%" in normalized
    assert "1,000.50元" in normalized
    assert "C00000232522022021915133" in normalized
    assert "## 1.2 主险与附加险关系" in normalized


def test_normalizer_removes_obvious_api_error_lines():
    raw = "正常内容\nERROR: empty response from api\n仍然保留"

    normalized = MarkdownNormalizer().normalize(raw)

    assert "正常内容" in normalized
    assert "仍然保留" in normalized
    assert "empty response" not in normalized
