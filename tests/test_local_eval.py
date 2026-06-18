import json


def test_local_eval_uses_id_mapping_and_computes_edit_distance(tmp_path):
    from finix_restore.local_eval import evaluate_predictions

    pred_dir = tmp_path / "pred"
    gt_dir = tmp_path / "gt"
    pred_dir.mkdir()
    gt_dir.mkdir()
    (pred_dir / "afts-1.md").write_text("abcd", encoding="utf-8")
    (gt_dir / "uuid-1.md").write_text("abxd", encoding="utf-8")
    mapping_csv = tmp_path / "id_mapping.csv"
    mapping_csv.write_text("uuid,afts_id\nuuid-1,afts-1\n", encoding="utf-8")
    output = tmp_path / "metrics.json"

    result = evaluate_predictions(pred_dir, gt_dir, mapping_csv, output)

    assert result["file_count"] == 1
    assert result["missing_gt"] == []
    assert result["files"][0]["gt_file"] == "uuid-1.md"
    assert result["files"][0]["edit_distance"] == 1
    assert result["files"][0]["normalized_edit_distance"] == 0.25
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["mean_normalized_edit_distance"] == 0.25


def test_html_table_stats_counts_rows_cells_and_empty_cells():
    from finix_restore.local_eval import html_table_stats

    stats = html_table_stats("<table><tr><td>A</td><td></td></tr><tr><td>B</td><td>C</td></tr></table>")

    assert stats == {"tr": 2, "td": 4, "empty_td": 1}
