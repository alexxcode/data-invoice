import fitz
import os
import yaml
import re
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any
from .models import ForensicFinding, Severity
from .geometry import compute_iou

def parse_pdf_date(date_str: str) -> datetime:
    if not date_str:
        return None
    # PDF dates are like D:YYYYMMDDHHmmSSOHH'mm'
    date_str = date_str.replace("D:", "").split("Z")[0].split("-")[0].split("+")[0]
    try:
        date_str = date_str[:14]
        return datetime.strptime(date_str, "%Y%m%d%H%M%S")
    except Exception:
        return None

def analyze_metadata(pdf_path: str, doc: fitz.Document) -> List[ForensicFinding]:
    findings = []
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    suspicious_producers = config.get("metadata", {}).get("suspicious_producers", [])
    
    # 1. Incremental updates
    try:
        with open(pdf_path, "rb") as f:
            raw = f.read()
        n_eof = raw.count(b"%%EOF")
        if n_eof > 1:
            findings.append(ForensicFinding(
                technique="metadata",
                severity=Severity.MEDIUM,
                page=0,
                score=0.8,
                explanation=f"Se detectaron {n_eof} secuencias %%EOF, indicando modificación tras generación (incremental update)."
            ))
    except Exception:
        pass

    # 2. Date discrepancies
    creation_date = doc.metadata.get("creationDate", "")
    mod_date = doc.metadata.get("modDate", "")
    cd = parse_pdf_date(creation_date)
    md = parse_pdf_date(mod_date)
    
    if cd and md and md > cd:
        diff = md - cd
        if diff > timedelta(hours=24):
            findings.append(ForensicFinding(
                technique="metadata",
                severity=Severity.MEDIUM,
                page=0,
                score=0.7,
                explanation=f"La fecha de modificación es posterior a la de creación en >24h ({diff})."
            ))
        elif diff > timedelta(seconds=0):
            findings.append(ForensicFinding(
                technique="metadata",
                severity=Severity.LOW,
                page=0,
                score=0.4,
                explanation=f"La fecha de modificación es levemente posterior a la de creación ({diff})."
            ))

    # 3. Suspicious Producer/Creator
    producer = doc.metadata.get("producer", "") or ""
    creator = doc.metadata.get("creator", "") or ""
    for sp in suspicious_producers:
        if sp.lower() in producer.lower() or sp.lower() in creator.lower():
            findings.append(ForensicFinding(
                technique="metadata",
                severity=Severity.HIGH,
                page=0,
                score=0.95,
                explanation=f"Software editor sospechoso detectado en metadatos: {sp}"
            ))
            break
            
    # 4. Orphan XMP
    try:
        xmp = doc.xref_xml_metadata()
        if xmp:
            if isinstance(xmp, str):
                xmp_lower = xmp.lower()
                if "xmpmm:history" in xmp_lower or "photoshop:" in xmp_lower or 'action="saved"' in xmp_lower:
                    findings.append(ForensicFinding(
                        technique="metadata",
                        severity=Severity.MEDIUM,
                        page=0,
                        score=0.75,
                        explanation="Trazas de edición de imagen (XMP History / Photoshop) en metadatos XML."
                    ))
    except Exception:
        pass

    # 5 & 6. Overlapped text and Anomalous fonts
    digit_regex = re.compile(r'[\d.,]{2,}')
    for page_idx, page in enumerate(doc):
        text_dict = page.get_text("dict")
        spans = []
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:  # text block
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        spans.append(span)
                    
        # 5. Overlapped text: un único finding por página con el peor par y el
        # conteo total (antes se emitía un finding HIGH por CADA par solapado,
        # inflando el riesgo en documentos con tablas densas).
        overlap_count = 0
        worst = None  # (iou, bbox)
        for i, spanA in enumerate(spans):
            for j in range(i + 1, len(spans)):
                spanB = spans[j]
                if not (spanA["text"].strip() and spanB["text"].strip()):
                    continue
                iou = compute_iou(spanA["bbox"], spanB["bbox"])
                if iou > 0.3:
                    overlap_count += 1
                    if worst is None or iou > worst[0]:
                        worst = (iou, spanA["bbox"])
        if worst is not None:
            findings.append(ForensicFinding(
                technique="metadata",
                severity=Severity.HIGH,
                page=page_idx,
                bbox=worst[1],
                score=0.85,
                explanation=(
                    f"Texto superpuesto detectado en {overlap_count} par(es) de spans "
                    f"(IoU máximo {worst[0]:.2f}). Posible parcheado."
                )
            ))

        # 6. Anomalous fonts. La heurística "fuente usada UNA vez" solo es
        # informativa si la página tiene suficientes spans como base de
        # comparación; con pocos spans toda fuente es "única" (FP garantizado).
        min_spans = config.get("metadata", {}).get("min_spans_for_font_rule", 5)
        if len(spans) < min_spans:
            continue

        font_counts = {}
        for span in spans:
            font = span.get("font", "Unknown")
            font_counts[font] = font_counts.get(font, 0) + 1

        for span in spans:
            font = span.get("font", "Unknown")
            if font_counts.get(font, 0) == 1 and digit_regex.search(span.get("text", "")):
                findings.append(ForensicFinding(
                    technique="metadata",
                    severity=Severity.MEDIUM,
                    page=page_idx,
                    bbox=span["bbox"],
                    score=0.7,
                    explanation=f"Fuente anómala '{font}' detectada en un único span numérico."
                ))

    return findings
