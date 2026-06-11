import fitz
import numpy as np

from app.forensics.models import DocumentClass
from app.forensics.typography import analyze_typography, regularized_inv_cov


def make_native_pdf():
    """PDF nativo con varios montos en texto vectorial (sin OCR)."""
    doc = fitz.open()
    page = doc.new_page()
    amounts = ["123,45", "678,90", "111,11", "222,22", "333,33", "444,44", "555,55"]
    for i, amt in enumerate(amounts):
        page.insert_text((72, 100 + i * 20), f"Concepto {i}: {amt} EUR", fontsize=11)
    page.insert_text((72, 260), "TOTAL: 2.469,10 EUR", fontsize=14)
    return doc


def test_typography_is_deterministic():
    # Antes se sumaba ruido gaussiano SIN SEMILLA a las features: dos corridas
    # sobre el mismo documento podían dar findings distintos. Este test fija
    # el contrato de determinismo.
    doc = make_native_pdf()
    runs = []
    for _ in range(3):
        findings = analyze_typography(doc, DocumentClass.NATIVE_DIGITAL)
        runs.append([f.model_dump() for f in findings])
    assert runs[0] == runs[1] == runs[2]


def test_typography_bboxes_in_page_points():
    # Los bboxes emitidos deben caer dentro del rect de la página (espacio de
    # puntos PDF), no en píxeles de un render a 150/300 dpi.
    doc = make_native_pdf()
    page_rect = doc[0].rect
    findings = analyze_typography(doc, DocumentClass.NATIVE_DIGITAL)
    for f in findings:
        assert f.bbox is not None
        x0, y0, x1, y1 = f.bbox
        assert 0 <= x0 <= x1 <= page_rect.width + 1
        assert 0 <= y0 <= y1 <= page_rect.height + 1


def test_regularized_inv_cov_handles_singular_matrix():
    # Columna constante -> covarianza singular. La regularización ridge debe
    # invertir sin excepciones y de forma determinista.
    X = np.array([[1.0, 2.0, 3.0]] * 10 + [[1.0, 2.5, 3.5]] * 5)
    inv1 = regularized_inv_cov(X)
    inv2 = regularized_inv_cov(X)
    assert np.array_equal(inv1, inv2)
    assert np.all(np.isfinite(inv1))
