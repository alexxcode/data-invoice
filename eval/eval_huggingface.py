"""Evaluación forense sobre documentos reales (HuggingFace) con scoring honesto.

Correcciones de Fase 0 (powerUp.md §4) respecto a la versión anterior:
1. **Localización IoU**: un "hit" exige que algún finding del módulo tenga
   IoU >= 0.2 contra la máscara ground-truth (antes bastaba que el módulo
   disparara en cualquier parte de la página, contando como TP lo que podía
   ser una falsa alarma coincidente). Se reportan ambas métricas.
2. **Split calibración/test determinista** (por paridad del índice de doc):
   los umbrales se calibran en `calib` y se reporta en `test`. Nunca sobre
   el mismo set.
3. **Semillas fijas** en los inyectores (reproducibilidad).
4. **Modo replay local** (`--local_dir`): re-evalúa los artefactos ya
   generados en disco sin red, para que cualquier revisor reproduzca la
   tabla offline.

Uso:
    python eval/eval_huggingface.py --local_dir data/hf_eval --split test
    python eval/eval_huggingface.py --batch_size 10 --start_idx 0 --split all
"""
import argparse
import json
import os
import random
import re
import sys

import fitz
import numpy as np
from PIL import Image

# Repo root en sys.path: el script debe correr desde cualquier cwd
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tamper_injector import (  # noqa: E402
    create_hard_negative,
    inject_clone_region,
    inject_digit_swap,
    inject_region_patch,
)
from app.forensics.classifier import classify_document  # noqa: E402
from app.forensics.copy_move import analyze_copy_move  # noqa: E402
from app.forensics.ela import analyze_ela  # noqa: E402
from app.forensics.geometry import bbox_from_mask, compute_iou, normalize_bbox  # noqa: E402
from app.forensics.noise import analyze_noise  # noqa: E402
from app.forensics.typography import analyze_typography  # noqa: E402

IOU_THRESHOLD = 0.2

# Módulo evaluado -> (técnicas que cuentan, sufijo de ataque que debe detectar)
MODULES = {
    "typography": ({"typography"}, "swap"),
    "ela_noise": ({"ela", "noise"}, "patch"),
    "copy_move": ({"copy_move"}, "clone"),
}


def evaluate_document(file_path):
    doc = fitz.open(file_path)
    doc_class = classify_document(doc)
    findings = []
    findings.extend(analyze_typography(doc, doc_class))
    findings.extend(analyze_copy_move(doc, doc_class))
    findings.extend(analyze_ela(doc, doc_class))
    findings.extend(analyze_noise(doc, doc_class))
    page_rect = doc[0].rect
    doc.close()
    return findings, (page_rect.width, page_rect.height)


def normalized_mask_bbox(mask_path):
    """Bbox de la región manipulada en coordenadas relativas [0,1]."""
    mask = np.array(Image.open(mask_path).convert("L"))
    bbox = bbox_from_mask(mask > 0)
    if bbox is None:
        return None
    h, w = mask.shape
    return normalize_bbox(bbox, w, h)


def module_hits(findings, page_dims, techniques, mask_path):
    """(hit a nivel página, hit localizado IoU>=umbral) para un módulo."""
    relevant = [f for f in findings if f.technique in techniques]
    page_hit = len(relevant) > 0
    if not page_hit or mask_path is None or not os.path.exists(mask_path):
        return page_hit, False
    gt_bbox = normalized_mask_bbox(mask_path)
    if gt_bbox is None:
        return page_hit, False
    w, h = page_dims
    for f in relevant:
        if f.bbox is None:
            continue
        if compute_iou(normalize_bbox(f.bbox, w, h), gt_bbox) >= IOU_THRESHOLD:
            return True, True
    return True, False


def build_cases(doc_idx, out_dir, base_path, regenerate):
    """Casos (img, mask, label, attack) de un documento; inyecta con semilla fija."""
    prefix = os.path.join(out_dir, f"doc_{doc_idx}")
    specs = [
        ("clean", f"{prefix}_clean.jpg", None, create_hard_negative),
        ("patch", f"{prefix}_patch.jpg", f"{prefix}_patch_mask.png", inject_region_patch),
        ("swap", f"{prefix}_swap.jpg", f"{prefix}_swap_mask.png", inject_digit_swap),
        ("clone", f"{prefix}_clone.jpg", f"{prefix}_clone_mask.png", inject_clone_region),
    ]
    cases = []
    for attack, img_path, mask_path, inject_fn in specs:
        exists = os.path.exists(img_path) and (mask_path is None or os.path.exists(mask_path))
        if regenerate or not exists:
            # Semilla derivada del doc y el ataque: corridas reproducibles
            random.seed(f"cotejo-{doc_idx}-{attack}")
            if mask_path is None:
                inject_fn(base_path, img_path)
            else:
                inject_fn(base_path, img_path, mask_path)
        label = "clean" if attack == "clean" else "tampered"
        cases.append((img_path, mask_path, label, attack))
    return cases


def in_split(doc_idx, split):
    if split == "all":
        return True
    return (doc_idx % 2 == 0) == (split == "calib")


def find_local_docs(local_dir):
    pattern = re.compile(r"doc_(\d+)_base\.jpg$")
    indices = []
    for name in os.listdir(local_dir):
        m = pattern.match(name)
        if m:
            indices.append(int(m.group(1)))
    return sorted(indices)


def iter_documents(args):
    """Genera (doc_idx, base_path) según el modo (replay local o streaming HF)."""
    out_dir = args.local_dir or os.path.join("data", "hf_eval")
    os.makedirs(out_dir, exist_ok=True)

    if args.local_dir:
        for doc_idx in find_local_docs(args.local_dir):
            yield doc_idx, os.path.join(args.local_dir, f"doc_{doc_idx}_base.jpg"), out_dir
        return

    from datasets import load_dataset
    print("Loading HuggingFace dataset in streaming mode...")
    dataset = load_dataset("mychen76/invoices-and-receipts_ocr_v1", split="train", streaming=True)
    iterator = iter(dataset)
    for _ in range(args.start_idx):
        next(iterator)
    for i in range(args.batch_size):
        try:
            item = next(iterator)
        except StopIteration:
            return
        doc_idx = args.start_idx + i
        base_path = os.path.join(out_dir, f"doc_{doc_idx}_base.jpg")
        if not os.path.exists(base_path):
            item["image"].convert("RGB").save(base_path, "JPEG", quality=95)
        yield doc_idx, base_path, out_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch_size", type=int, default=5, help="Docs a descargar (modo streaming)")
    parser.add_argument("--start_idx", type=int, default=0, help="Offset en el dataset HF")
    parser.add_argument("--local_dir", type=str, default=None,
                        help="Replay offline sobre artefactos existentes (ej. data/hf_eval)")
    parser.add_argument("--split", choices=["all", "calib", "test"], default="all",
                        help="calib = docs pares, test = docs impares")
    parser.add_argument("--regenerate", action="store_true",
                        help="Regenera las variantes manipuladas (con semillas fijas)")
    parser.add_argument("--out_json", type=str, default=None, help="Guardar resultados crudos")
    args = parser.parse_args()

    stats = {m: {"pos": 0, "page_hits": 0, "loc_hits": 0, "neg": 0, "fp": 0} for m in MODULES}
    rows = []
    docs = 0

    for doc_idx, base_path, out_dir in iter_documents(args):
        if not in_split(doc_idx, args.split):
            continue
        print(f"\n--- Doc {doc_idx} (split={args.split}) ---")
        cases = build_cases(doc_idx, out_dir, base_path, args.regenerate)
        docs += 1

        for img_path, mask_path, label, attack in cases:
            print(f"  evaluando {os.path.basename(img_path)}...")
            findings, page_dims = evaluate_document(img_path)

            for module, (techniques, target_attack) in MODULES.items():
                page_hit, loc_hit = module_hits(findings, page_dims, techniques, mask_path)
                if label == "tampered":
                    if attack == target_attack:
                        stats[module]["pos"] += 1
                        stats[module]["page_hits"] += int(page_hit)
                        stats[module]["loc_hits"] += int(loc_hit)
                else:
                    stats[module]["neg"] += 1
                    stats[module]["fp"] += int(page_hit)

            rows.append({
                "doc": doc_idx, "attack": attack, "label": label,
                "findings": [
                    {"technique": f.technique, "severity": f.severity.value,
                     "score": f.score, "bbox": f.bbox}
                    for f in findings
                ],
            })

    print(f"\n================ RESULTADOS FORENSES (split={args.split}, docs={docs}) ================")
    print(f"{'Módulo':<12} {'APCER pág.':<12} {'APCER loc.':<12} {'BPCER':<8} {'pos':<5} {'neg':<5}")
    for module, s in stats.items():
        apcer_page = (1 - s["page_hits"] / s["pos"]) * 100 if s["pos"] else float("nan")
        apcer_loc = (1 - s["loc_hits"] / s["pos"]) * 100 if s["pos"] else float("nan")
        bpcer = s["fp"] / s["neg"] * 100 if s["neg"] else float("nan")
        print(f"{module:<12} {apcer_page:<12.1f} {apcer_loc:<12.1f} {bpcer:<8.1f} {s['pos']:<5} {s['neg']:<5}")
    print("\nAPCER pág. = ataque no detectado en la página | APCER loc. = no detectado con IoU>=0.2 "
          "contra la máscara GT | BPCER = falsa alarma en documento limpio")

    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump({"split": args.split, "docs": docs, "stats": stats, "rows": rows}, f, indent=2)
        print(f"Resultados crudos guardados en {args.out_json}")


if __name__ == "__main__":
    main()
