import yaml
import os
import fitz
from typing import List, Tuple
from .models import ForensicFinding, ForensicReport, Severity, DocumentClass
from .classifier import classify_document
from .metadata import analyze_metadata
from .typography import analyze_typography
from .ela import analyze_ela
from .noise import analyze_noise
from .copy_move import analyze_copy_move
from .overlays import generate_overlays
from concurrent.futures import ThreadPoolExecutor

def get_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def compute_iou(boxA, boxB):
    if not boxA or not boxB: return 0.0
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    if interArea == 0: return 0.0
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    return interArea / float(boxAArea + boxBArea - interArea)

def score_findings(findings: List[ForensicFinding], doc_class: DocumentClass) -> Tuple[float, bool, List[ForensicFinding]]:
    config = get_config()
    weights = {}
    for module in ["metadata", "ela", "copy_move", "noise", "typography"]:
        w = config.get(module, {}).get("weights", {}).get(module, 0.5)
        weights[module] = w
        
    scorer_config = config.get("scorer", {})
    req_review_thresh = scorer_config.get("requires_review_risk_threshold", 0.60)
    
    # Regla de refuerzo cruzado
    n = len(findings)
    for i in range(n):
        for j in range(i+1, n):
            f1, f2 = findings[i], findings[j]
            if f1.technique != f2.technique and f1.page == f2.page and f1.bbox and f2.bbox:
                if compute_iou(f1.bbox, f2.bbox) > 0.3:
                    f1.severity = Severity.HIGH
                    f2.severity = Severity.HIGH
                    f1.score = min(1.0, f1.score * 2)
                    f2.score = min(1.0, f2.score * 2)

    risk_product = 1.0
    requires_review = False
    
    for f in findings:
        w = weights.get(f.technique, 0.5)
        risk_product *= (1.0 - w * f.score)
        if f.severity == Severity.HIGH:
            requires_review = True
            
    forensic_risk = 1.0 - risk_product
    
    if forensic_risk > req_review_thresh:
        requires_review = True
        
    return forensic_risk, requires_review, findings

def run_forensics(pdf_path: str) -> ForensicReport:
    doc = fitz.open(pdf_path)
    doc_class = classify_document(doc)
    
    findings = []
    
    # Run independent techniques in parallel using threads
    with ThreadPoolExecutor(max_workers=4) as executor:
        f_meta = executor.submit(analyze_metadata, pdf_path, doc)
        f_ela = executor.submit(analyze_ela, doc, doc_class)
        f_noise = executor.submit(analyze_noise, doc, doc_class)
        f_copy = executor.submit(analyze_copy_move, doc, doc_class)
        
        findings.extend(f_meta.result())
        findings.extend(f_ela.result())
        findings.extend(f_noise.result())
        findings.extend(f_copy.result())
        
    # Typography runs after
    findings.extend(analyze_typography(doc, doc_class))
    
    risk, review, scored_findings = score_findings(findings, doc_class)
    
    # Generate overlays
    base_name = os.path.basename(pdf_path).split('.')[0]
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "overlays", base_name)
    generate_overlays(doc, scored_findings, out_dir)
    
    return ForensicReport(
        document_class=doc_class,
        findings=scored_findings,
        forensic_risk=risk,
        requires_review=review
    )
