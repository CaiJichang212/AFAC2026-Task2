from finix_restore.eval.io import load_pairs


def _write_csv(path, rows):
    lines = ["file_name,ground_truth"]
    lines.extend(f"{name},{text}" for name, text in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_pairs_csv_matched(tmp_path):
    pred = tmp_path / "pred.csv"
    gt = tmp_path / "gt.csv"
    _write_csv(pred, [("doc_001.png", "hello"), ("doc_002.png", "world")])
    _write_csv(gt, [("doc_001.png", "hi"), ("doc_002.png", "world")])

    pairs, missing_gt, missing_pred = load_pairs(pred, gt)

    names = {name for name, _, _ in pairs}
    assert names == {"doc_001.png", "doc_002.png"}
    by_name = {name: (p, g) for name, p, g in pairs}
    assert by_name["doc_001.png"] == ("hello", "hi")
    assert missing_gt == []
    assert missing_pred == []


def test_load_pairs_csv_missing(tmp_path):
    pred = tmp_path / "pred.csv"
    gt = tmp_path / "gt.csv"
    _write_csv(pred, [("a.png", "pa"), ("b.png", "pb")])
    _write_csv(gt, [("a.png", "ga"), ("c.png", "gc")])

    pairs, missing_gt, missing_pred = load_pairs(pred, gt)

    assert [name for name, _, _ in pairs] == ["a.png"]
    assert missing_gt == ["b.png"]
    assert missing_pred == ["c.png"]


def test_load_pairs_dir_with_mapping(tmp_path):
    pred = tmp_path / "pred.csv"
    _write_csv(pred, [("afts-1.png", "pred-text")])

    mds = tmp_path / "mds"
    mds.mkdir()
    (mds / "uuid-1.md").write_text("gt-text", encoding="utf-8")

    mapping = tmp_path / "id_mapping.csv"
    mapping.write_text("uuid,afts_id\nuuid-1,afts-1\n", encoding="utf-8")

    pairs, missing_gt, missing_pred = load_pairs(pred, mds, mapping_csv=mapping)

    assert pairs == [("afts-1.png", "pred-text", "gt-text")]
    assert missing_gt == []
    assert missing_pred == []
