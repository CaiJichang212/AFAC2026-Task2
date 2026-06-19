"""Pure geometry helpers for chunk planning.

These functions are intentionally side-effect free: they take primitive
inputs (ints, tuples, lists) and return primitive outputs so the chunkers
can compose them without coupling to filesystem or pipeline state.
"""
from __future__ import annotations


def box_pixels(box: tuple[int, int, int, int]) -> int:
    """Return pixel count covered by an (x0, y0, x1, y1) box."""
    x0, y0, x1, y1 = box
    width = max(0, x1 - x0)
    height = max(0, y1 - y0)
    return width * height


def expand_box(
    box: tuple[int, int, int, int],
    margin: int,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """Expand a box by ``margin`` on every side, clamped to image bounds."""
    x0, y0, x1, y1 = box
    nx0 = max(0, x0 - margin)
    ny0 = max(0, y0 - margin)
    nx1 = min(width, x1 + margin)
    ny1 = min(height, y1 + margin)
    return (nx0, ny0, nx1, ny1)


def nearest_band_center(
    target: int,
    bands: list[tuple[int, int]],
    search_px: int,
) -> tuple[int, str]:
    """Find a blank-band center near ``target`` within ``search_px`` distance.

    Returns ``(center, "blank_band")`` when a candidate is found, else
    ``(target, "fixed_cut")``.
    """
    candidates: list[tuple[int, int]] = []
    for b0, b1 in bands:
        center = (b0 + b1) // 2
        if abs(center - target) <= search_px:
            candidates.append((abs(center - target), center))
    if not candidates:
        return target, "fixed_cut"
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1], "blank_band"


def traceable_chunk_name(
    stem: str,
    row: int,
    col: int,
    bbox: tuple[int, int, int, int],
) -> str:
    """Produce a human-traceable filename encoding row/col/bbox."""
    x0, y0, x1, y1 = bbox
    width = x1 - x0
    height = y1 - y0
    return f"{stem}__r{row}_c{col}__x{x0}_y{y0}_w{width}_h{height}.jpg"


def overlap_dict(
    row: int,
    col: int,
    rows: int,
    cols: int,
    horizontal: int,
    vertical: int,
) -> dict[str, int]:
    """Build the per-cell overlap dictionary for a grid.

    Cells on the boundary do not extend beyond the image, so the
    corresponding side reports zero overlap.
    """
    return {
        "left": horizontal if col > 0 else 0,
        "right": horizontal if col < cols - 1 else 0,
        "top": vertical if row > 0 else 0,
        "bottom": vertical if row < rows - 1 else 0,
    }
