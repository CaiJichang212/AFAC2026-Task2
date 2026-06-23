from finix_restore.eval.reading_order import read_order_edit, split_blocks


def test_split_blocks_kinds_and_count():
    blocks = split_blocks("# Title\n\npara one\n\n## Sub\n\npara two")
    assert len(blocks) == 4
    assert blocks[0].startswith("h:")
    assert blocks[1].startswith("p:")
    assert blocks[2].startswith("h:")


def test_read_order_edit_identical_is_zero():
    text = "# A\n\nbody a\n\n# B\n\nbody b"
    assert read_order_edit(text, text) == 0.0


def test_read_order_edit_swapped_order_is_positive():
    gt = "# A\n\nbody a\n\n# B\n\nbody b"
    pred = "# B\n\nbody b\n\n# A\n\nbody a"
    assert read_order_edit(pred, gt) > 0.0


def test_read_order_edit_empty_gt_is_one():
    assert read_order_edit("# A body", "") == 1.0


def test_read_order_edit_insensitive_to_paragraph_spacing():
    # GT uses single-newline separation, prediction uses blank-line separation.
    # Splitting per non-empty line makes both comparable, so identical content
    # scores 0 regardless of spacing style.
    gt = "# A\nbody a\n## B\nbody b"
    pred = "# A\n\nbody a\n\n## B\n\nbody b"
    assert read_order_edit(pred, gt) == 0.0


def test_split_blocks_keeps_html_table_as_single_unit():
    text = "# Title\n<table><tr><td>a</td></tr>\n<tr><td>b</td></tr></table>\npara"
    blocks = split_blocks(text)
    assert len(blocks) == 3
    assert blocks[0].startswith("h:")
    assert blocks[1].startswith("t:")
    assert blocks[2].startswith("p:")

