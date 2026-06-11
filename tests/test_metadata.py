import fitz

from app.forensics.metadata import analyze_metadata


def save_and_analyze(doc, tmp_path, name="doc.pdf"):
    path = str(tmp_path / name)
    doc.save(path)
    saved = fitz.open(path)
    return analyze_metadata(path, saved)


def test_clean_pdf_no_findings(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Factura limpia. Total: 121,00 EUR", fontsize=11)
    findings = save_and_analyze(doc, tmp_path)
    assert findings == []


def test_overlapped_text_deduplicated(tmp_path):
    # Tres spans superpuestos en el mismo punto generan varios pares con
    # IoU > 0.3, pero deben colapsar a UN finding por página (antes se emitía
    # uno por par, inflando el riesgo en documentos densos).
    doc = fitz.open()
    page = doc.new_page()
    for _ in range(3):
        page.insert_text((100, 100), "Total: 999,99", fontsize=12)
    findings = save_and_analyze(doc, tmp_path)
    overlapped = [f for f in findings if "superpuesto" in f.explanation]
    assert len(overlapped) == 1
    assert "par(es)" in overlapped[0].explanation


def test_suspicious_producer_detected(tmp_path):
    doc = fitz.open()
    doc.new_page()
    doc.set_metadata({"producer": "Adobe Photoshop CC 2024"})
    findings = save_and_analyze(doc, tmp_path)
    assert any("Photoshop" in f.explanation for f in findings)
