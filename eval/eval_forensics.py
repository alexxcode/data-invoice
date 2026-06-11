"""[LEGADO — Fase 0] Scoring a nivel página sobre data/tampered_eval.

Superseded por eval/eval_huggingface.py, que añade localización IoU contra
máscaras GT, split calibración/test y semillas fijas. Se conserva solo como
referencia histórica; no usar sus números en el README.
"""
import os
import json
import sys

import fitz
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.forensics.models import DocumentClass
from app.forensics.classifier import classify_document
from app.forensics.metadata import analyze_metadata
from app.forensics.ela import analyze_ela
from app.forensics.noise import analyze_noise
from app.forensics.copy_move import analyze_copy_move
from app.forensics.typography import analyze_typography

def compute_iou(boxA, boxB):
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    iou = interArea / float(boxAArea + boxBArea - interArea) if (boxAArea + boxBArea - interArea) > 0 else 0
    return iou

def evaluate_dataset(gt_path):
    with open(gt_path, "r") as f:
        ground_truth = json.load(f)
        
    metrics = {
        "typography": {"apcer": 0, "bpcer": 0, "pos": 0, "neg": 0, "hits": 0, "false_alarms": 0},
        "ela_noise": {"apcer": 0, "bpcer": 0, "pos": 0, "neg": 0, "hits": 0, "false_alarms": 0},
        "copy_move": {"apcer": 0, "bpcer": 0, "pos": 0, "neg": 0, "hits": 0, "false_alarms": 0},
    }
    
    for item in ground_truth:
        file_path = item["image"]
        tamper_type = item["type"]
        is_tampered = item["class"] == "tampered"
        
        # fitz.open can open images directly without wrapping them
        pdf_to_analyze = file_path
            
        try:
            doc = fitz.open(pdf_to_analyze)
            doc_class = classify_document(doc)
            
            # Run specific techniques
            findings = []
            findings.extend(analyze_typography(doc, doc_class))
            findings.extend(analyze_copy_move(doc, doc_class))
            findings.extend(analyze_ela(doc, doc_class))
            findings.extend(analyze_noise(doc, doc_class))
            
            # Classify findings by category
            typo_alert = any(f.technique == "typography" for f in findings)
            ela_noise_alert = any(f.technique in ("ela", "noise") for f in findings)
            cm_alert = any(f.technique == "copy_move" for f in findings)
            
            if is_tampered:
                if tamper_type == "digit_swap":
                    metrics["typography"]["pos"] += 1
                    metrics["copy_move"]["pos"] += 1
                    if typo_alert: metrics["typography"]["hits"] += 1
                    if cm_alert: metrics["copy_move"]["hits"] += 1
                elif tamper_type in ("region_patch", "resave_chain"):
                    metrics["ela_noise"]["pos"] += 1
                    if ela_noise_alert: metrics["ela_noise"]["hits"] += 1
                    if tamper_type == "region_patch":
                        metrics["copy_move"]["pos"] += 1
                        if cm_alert: metrics["copy_move"]["hits"] += 1
            else:
                metrics["typography"]["neg"] += 1
                metrics["ela_noise"]["neg"] += 1
                metrics["copy_move"]["neg"] += 1
                
                if typo_alert: metrics["typography"]["false_alarms"] += 1
                if ela_noise_alert: metrics["ela_noise"]["false_alarms"] += 1
                if cm_alert: metrics["copy_move"]["false_alarms"] += 1

        except Exception as e:
            print(f"Error evaluating {file_path}: {e}")
        finally:
            pass

    # Calculate final APCER/BPCER
    for cat, stats in metrics.items():
        if stats["pos"] > 0:
            stats["apcer"] = 1.0 - (stats["hits"] / stats["pos"])
        if stats["neg"] > 0:
            stats["bpcer"] = stats["false_alarms"] / stats["neg"]
            
    print("================== RESULTADOS FORENSES ==================")
    for cat, stats in metrics.items():
        print(f"[{cat}] APCER: {stats['apcer']*100:.1f}% | BPCER: {stats['bpcer']*100:.1f}% (Pos: {stats['pos']}, Neg: {stats['neg']})")
    
    return metrics

if __name__ == "__main__":
    gt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tampered_eval", "ground_truth.json")
    evaluate_dataset(gt_path)
