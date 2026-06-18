import json

from PIL import Image

from finix_restore.profiler import ImageProfiler


def test_profiler_classifies_long_strip(tmp_path):
    image_path = tmp_path / "long.jpg"
    Image.new("RGB", (100, 1200), "white").save(image_path)

    profile = ImageProfiler().profile(image_path)

    assert profile.width == 100
    assert profile.height == 1200
    assert profile.doc_type == "long_strip"


def test_profiler_classifies_large_table_page_without_filename_hint(tmp_path):
    image_path = tmp_path / "sample.jpg"
    Image.new("RGB", (4000, 5600), "white").save(image_path)

    profile = ImageProfiler().profile(image_path)

    assert profile.doc_type == "table_page"
    assert profile.pixels == 22_400_000


def test_profiler_marks_extreme_pixel_risk_and_writes_json(tmp_path):
    image_path = tmp_path / "huge.jpg"
    Image.new("RGB", (8000, 8000), "white").save(image_path)
    out_dir = tmp_path / "profiles"

    profile = ImageProfiler().profile_and_write(image_path, out_dir)
    payload = json.loads((out_dir / "huge.json").read_text(encoding="utf-8"))

    assert profile.risk_level == "extreme"
    assert payload["width"] == 8000
    assert payload["height"] == 8000
    assert payload["doc_type"] == profile.doc_type
