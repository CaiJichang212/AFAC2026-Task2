from __future__ import annotations

import csv
import json

from finix_restore.eval.cli import main


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file_name", "ground_truth"])
        writer.writerows(rows)


def test_main_csv_mode(tmp_path, capsys):
    pred = tmp_path / "pred.csv"
    gt = tmp_path / "gt.csv"
    out = tmp_path / "report.json"

    _write_csv(pred, [["d.png", "# Title"]])
    _write_csv(gt, [["d.png", "# Title"]])

    rc = main(["--pred", str(pred), "--gt", str(gt), "--output", str(out)])
    assert rc == 0

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["file_count"] == 1

    captured = capsys.readouterr()
    assert "Overall" in captured.out
