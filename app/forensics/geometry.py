"""Espacio de coordenadas canónico de la capa forense.

Todo ForensicFinding.bbox se expresa en PUNTOS PDF (72 dpi), el mismo espacio
que devuelve page.get_text() y que consumen los overlays. Los detectores que
trabajan sobre renders o imágenes embebidas deben convertir con estas
funciones antes de emitir un finding. El refuerzo cruzado por IoU del scorer
solo es válido si todos los módulos respetan este contrato.
"""
from typing import Optional, Tuple

import fitz
import numpy as np

Bbox = Tuple[float, float, float, float]


def compute_iou(boxA: Optional[Bbox], boxB: Optional[Bbox]) -> float:
    if not boxA or not boxB:
        return 0.0
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    inter = max(0.0, xB - xA) * max(0.0, yB - yA)
    if inter == 0:
        return 0.0
    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    union = areaA + areaB - inter
    return inter / union if union > 0 else 0.0


def pixels_to_points(bbox: Bbox, dpi: float) -> Bbox:
    """Convierte un bbox en píxeles de un render a `dpi` al espacio de puntos PDF."""
    s = 72.0 / dpi
    return (bbox[0] * s, bbox[1] * s, bbox[2] * s, bbox[3] * s)


def normalize_bbox(bbox: Bbox, width: float, height: float) -> Bbox:
    """Lleva un bbox a coordenadas relativas [0,1] (para comparar entre espacios)."""
    if width <= 0 or height <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (bbox[0] / width, bbox[1] / height, bbox[2] / width, bbox[3] / height)


def image_bbox_to_page_points(
    page: fitz.Page, xref: int, bbox_img_px: Bbox, img_w: int, img_h: int
) -> Bbox:
    """Mapea un bbox en píxeles de una imagen embebida al rect de la página donde
    está colocada (en puntos). Si no se puede resolver la colocación, asume que
    la imagen cubre la página completa (caso típico de scans e image-documents)."""
    rect = None
    try:
        rects = page.get_image_rects(xref)
        if rects:
            rect = rects[0]
    except Exception:
        rect = None
    if rect is None:
        rect = page.rect
    if img_w <= 0 or img_h <= 0:
        return (rect.x0, rect.y0, rect.x1, rect.y1)
    sx = rect.width / img_w
    sy = rect.height / img_h
    x0, y0, x1, y1 = bbox_img_px
    return (rect.x0 + x0 * sx, rect.y0 + y0 * sy, rect.x0 + x1 * sx, rect.y0 + y1 * sy)


def bbox_from_mask(mask: np.ndarray) -> Optional[Bbox]:
    """Bbox (en píxeles de la máscara) de la región no-cero de una máscara binaria."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))
