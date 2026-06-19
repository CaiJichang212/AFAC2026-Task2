from finix_restore.chunk_geometry import (
    box_pixels,
    expand_box,
    nearest_band_center,
    overlap_dict,
    traceable_chunk_name,
)


def test_box_pixels():
    # (x1-x0) * (y1-y0) = 20 * 30 = 600
    assert box_pixels((10, 20, 30, 50)) == 600
    assert box_pixels((0, 0, 0, 0)) == 0
    assert box_pixels((5, 5, 15, 25)) == 200


def test_expand_box_clamps_to_bounds():
    assert expand_box((10, 20, 30, 50), margin=5, width=100, height=100) == (5, 15, 35, 55)
    # margin pushes beyond bounds; clamp to [0, width] / [0, height]
    assert expand_box((2, 3, 90, 95), margin=10, width=100, height=100) == (0, 0, 100, 100)
    # margin = 0 keeps the box
    assert expand_box((1, 2, 3, 4), margin=0, width=100, height=100) == (1, 2, 3, 4)


def test_nearest_band_center_returns_blank_band_when_inside_search():
    center, source = nearest_band_center(100, [(80, 90), (105, 115)], search_px=20)
    assert (center, source) == (110, "blank_band")


def test_nearest_band_center_returns_fixed_cut_when_outside_search():
    center, source = nearest_band_center(100, [(0, 5), (300, 320)], search_px=20)
    assert (center, source) == (100, "fixed_cut")


def test_nearest_band_center_with_empty_bands():
    center, source = nearest_band_center(100, [], search_px=20)
    assert (center, source) == (100, "fixed_cut")


def test_traceable_chunk_name():
    assert (
        traceable_chunk_name("doc", 1, 2, (10, 20, 110, 220))
        == "doc__r1_c2__x10_y20_w100_h200.jpg"
    )


def test_overlap_dict_zeros_at_boundaries():
    assert overlap_dict(0, 1, 2, 2, 160, 220) == {
        "left": 160,
        "right": 0,
        "top": 0,
        "bottom": 220,
    }
    # interior cell should keep all overlaps
    assert overlap_dict(1, 1, 3, 3, 10, 20) == {
        "left": 10,
        "right": 10,
        "top": 20,
        "bottom": 20,
    }
    # single cell grid: every side is boundary
    assert overlap_dict(0, 0, 1, 1, 10, 20) == {
        "left": 0,
        "right": 0,
        "top": 0,
        "bottom": 0,
    }
