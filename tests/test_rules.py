from app.rules import run_deterministic_rules
from app.schema import FacturaEstructurada


def make_factura(numero="F-001", subtotal=100.0, impuestos=21.0, total=121.0,
                 cif="A12345678", cups="ES0021000000000000AA0F", auditable=True):
    prov = {"provenance": {"page": 1}}
    return FacturaEstructurada(
        es_documento_auditable=auditable,
        tipo_documento_detectado="Factura de Luz" if auditable else "Carta",
        extraction_confidence=0.95,
        numero_factura={"value": numero, **prov},
        emisor={"nombre": {"value": "Electrica S.A.", **prov}, "cif": {"value": cif, **prov}},
        cliente={"nombre": {"value": "Cliente", **prov}, "cups": {"value": cups, **prov}},
        conceptos=[],
        totales={
            "subtotal": {"value": subtotal, **prov},
            "impuestos": {"value": impuestos, **prov},
            "total_a_pagar": {"value": total, **prov},
        },
    )


def findings_for(facturas, numero):
    return run_deterministic_rules(facturas).get(numero, [])


def test_clean_invoice_no_findings():
    assert findings_for([make_factura()], "F-001") == []


def test_arithmetic_mismatch_detected():
    f = make_factura(total=999.99)
    hallazgos = findings_for([f], "F-001")
    assert any(h.tipo == "aritmética" and h.gravedad == "critical" for h in hallazgos)


def test_arithmetic_rounding_tolerance():
    # Diferencia de 0.01 por redondeo no debe alertar (tolerancia 0.05)
    f = make_factura(subtotal=100.0, impuestos=21.0, total=121.01)
    assert findings_for([f], "F-001") == []


def test_missing_cif_detected():
    f = make_factura(cif="  ")
    hallazgos = findings_for([f], "F-001")
    assert any(h.tipo == "faltante" and "CIF" in h.mensaje for h in hallazgos)


def test_short_cups_detected():
    f = make_factura(cups="ES123")
    hallazgos = findings_for([f], "F-001")
    assert any(h.tipo == "faltante" and "CUPS" in h.mensaje for h in hallazgos)


def test_duplicates_in_batch():
    a = make_factura(numero="F-DUP")
    b = make_factura(numero="F-DUP")
    hallazgos = findings_for([a, b], "F-DUP")
    assert any(h.tipo == "duplicado" for h in hallazgos)


def test_non_auditable_document_short_circuits():
    f = make_factura(auditable=False, total=999.99)
    hallazgos = findings_for([f], "F-001")
    assert len(hallazgos) == 1
    assert hallazgos[0].tipo == "documento_invalido"
