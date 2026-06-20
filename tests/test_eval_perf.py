from __future__ import annotations

import time

from finix_restore.eval.reading_order import read_order_edit
from finix_restore.eval.text_metric import text_edit


def test_text_edit_handles_long_document_fast():
    unit = "保险条款适用范围"
    gt = (unit * (20000 // len(unit) + 1))[:20000]
    pred = gt[:10000] + "XYZW" + gt[10004:]

    start = time.perf_counter()
    value = text_edit(pred, gt)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0
    assert 0 < value < 1


def test_read_order_edit_handles_many_blocks_fast():
    gt = "\n\n".join(f"# 标题{i}\n\n正文{i}" for i in range(400))
    pred = "\n\n".join(f"# 标题{i}\n\n正文{i}" for i in range(400) if i != 5)

    start = time.perf_counter()
    value = read_order_edit(pred, gt)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0
    assert value >= 0
