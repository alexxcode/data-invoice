import numpy as np

from app.forensics.geometry import (
    bbox_from_mask,
    compute_iou,
    normalize_bbox,
    pixels_to_points,
)


def test_iou_identical_boxes():
    assert compute_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0


def test_iou_disjoint_boxes():
    assert compute_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_iou_partial_overlap():
    # Solapamiento de 5x10 entre dos cajas de 10x10 -> 50/150
    iou = compute_iou((0, 0, 10, 10), (5, 0, 15, 10))
    assert abs(iou - 50 / 150) < 1e-9


def test_iou_none_inputs():
    assert compute_iou(None, (0, 0, 1, 1)) == 0.0
    assert compute_iou((0, 0, 1, 1), None) == 0.0


def test_pixels_to_points_150dpi():
    # 150 px a 150 dpi = 72 puntos (1 pulgada)
    bbox = pixels_to_points((0, 0, 150, 300), dpi=150)
    assert bbox == (0, 0, 72, 144)


def test_normalize_bbox():
    assert normalize_bbox((10, 20, 30, 40), 100, 200) == (0.1, 0.1, 0.3, 0.2)


def test_bbox_from_mask():
    mask = np.zeros((50, 50), dtype=np.uint8)
    mask[10:20, 30:40] = 1
    assert bbox_from_mask(mask) == (30.0, 10.0, 40.0, 20.0)


def test_bbox_from_empty_mask():
    assert bbox_from_mask(np.zeros((10, 10), dtype=np.uint8)) is None
