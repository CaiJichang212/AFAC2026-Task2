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


def test_normalizer_fixes_doubled_hash_headings_by_number_depth():
    raw = "\n".join(
        [
            "# # 1. 少儿特定疾病",
            "## # (1) 白血病",
            "# # 1.1 合同构成",
            "### # 1.1.1 赔付细则",
        ]
    )

    normalized = MarkdownNormalizer().normalize(raw)

    lines = normalized.splitlines()
    assert lines[0] == "## 1. 少儿特定疾病"
    assert lines[1] == "### (1) 白血病"
    assert lines[2] == "### 1.1 合同构成"
    assert lines[3] == "#### 1.1.1 赔付细则"
    assert "# #" not in normalized


def test_normalizer_collapses_doubled_hash_without_number():
    raw = "# # 条款目录\n## # 附则"

    normalized = MarkdownNormalizer().normalize(raw)

    assert normalized.splitlines()[0] == "# 条款目录"
    assert normalized.splitlines()[1] == "## 附则"


def test_normalizer_does_not_split_multi_level_headings():
    raw = "## 1. 总则\n### 1.1 投保\n#### 1.1.1 细则\n# 标题"

    normalized = MarkdownNormalizer().normalize(raw)

    assert normalized == "## 1. 总则\n### 1.1 投保\n#### 1.1.1 细则\n# 标题\n"


def test_normalizer_still_adds_space_after_hash_without_space():
    raw = "##1.1 保险责任\n###2.1.1 赔付"

    normalized = MarkdownNormalizer().normalize(raw)

    assert normalized == "## 1.1 保险责任\n### 2.1.1 赔付\n"


def test_normalizer_strips_code_fence_lines():
    raw = "```markdown\n# 标题\n正文\n```"

    normalized = MarkdownNormalizer().normalize(raw)

    assert normalized == "# 标题\n正文\n"
    assert "```" not in normalized


def test_normalizer_strips_fence_embedded_between_table_chunks():
    raw = "<table>\n<tr><td>a</td></tr>\n```\n```markdown\n<tr><td>b</td></tr>\n</table>"

    normalized = MarkdownNormalizer().normalize(raw)

    assert "```" not in normalized
    assert "<tr><td>a</td></tr>" in normalized
    assert "<tr><td>b</td></tr>" in normalized

