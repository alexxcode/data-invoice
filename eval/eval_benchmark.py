"""Evaluador del benchmark realista v1 (powerUp.md, Fase 1).

Consume el manifest generado por build_benchmark.py y produce la matriz
módulo × ataque × cadena de transmisión con APCER (página y localizado) y
BPCER. Escribe los hallazgos crudos por muestra a JSONL (resume-able) para que
la Fase 3 (fusión calibrada) los reutilice sin re-correr los detectores.

Uso:
    python eval/eval_benchmark.py --bench_dir data/benchmark_v1 --split test
    python eval/eval_benchmark.py --bench_dir data/benchmark_v1 --split all --resume
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import fitz
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.forensics.classifier import classify_document  # noqa: E402
from app.forensics.copy_move import analyze_copy_move  # noqa: E402
from app.forensics.ela import analyze_ela  # noqa: E402
from app.forensics.geometry import bbox_from_mask, compute_iou, normalize_bbox  # noqa: E402
from app.forensics.noise import analyze_noise  # noqa: E402
from app.forensics.typography import analyze_typography  # noqa: E402

IOU_THRESHOLD = 0.2
MODULE_TECHNIQUES = {
    "typography": {"typography"},
    "ela_noise": {"ela", "noise"},
    "copy_move": {"copy_move"},
}


def evaluate_image(path):
    doc = fitz.open(path)
    doc_class = classify_document(doc)
    findings = []
    findings.extend(analyze_typography(doc, doc_class))
    findings.extend(analyze_copy_move(doc, doc_class))
    findings.extend(analyze_ela(doc, doc_class))
    findings.extend(analyze_noise(doc, doc_class))
    rect = doc[0].rect
    doc.close()
    return findings, (rect.width, rect.height)


def gt_bbox_norm(mask_path):
    mask = np.array(Image.open(mask_path).convert("L"))
    bbox = bbox_from_mask(mask > 0)
    if bbox is None:
        return None
    h, w = mask.shape
    return normalize_bbox(bbox, w, h)


def module_hit(findings, page_dims, techniques, gt_norm):
    relevant = [f for f in findings if f.technique in techniques]
    page_hit = len(relevant) > 0
    loc_hit = False
    if page_hit and gt_norm is not None:
        w, h = page_dims
        for f in relevant:
            if f.bbox and compute_iou(normalize_bbox(f.bbox, w, h), gt_norm) >= IOU_THRESHOLD:
                loc_hit = True
                break
    return page_hit, loc_hit


def load_done(raw_path):
    done = {}
    if os.path.exists(raw_path):
        with open(raw_path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done[r["image"]] = r
                except Exception:
                    pass
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench_dir", default="data/benchmark_v1")
    ap.add_argument("--split", choices=["all", "calib", "test"], default="test")
    ap.add_argument("--resume", action="store_true", help="reutiliza hallazgos ya computados")
    args = ap.parse_args()

    manifest = os.path.join(args.bench_dir, "manifest.jsonl")
    rows = [json.loads(l) for l in open(manifest, encoding="utf-8")]
    if args.split != "all":
        rows = [r for r in rows if r["split"] == args.split]

    # Caché de hallazgos independiente del split: los detectores se corren una
    # vez por imagen; calib/test solo filtran qué filas se agregan. Así
    # `--split test --resume` reutiliza lo computado por `--split all`.
    raw_path = os.path.join(args.bench_dir, "findings_all.jsonl")
    done = load_done(raw_path) if args.resume else {}
    raw_out = open(raw_path, "a" if args.resume else "w", encoding="utf-8")

    # Acumuladores: por (module, attack, chain)
    acc = defaultdict(lambda: {"pos": 0, "page": 0, "loc": 0, "neg": 0, "fp": 0})

    for i, r in enumerate(rows):
        img_path = os.path.join(args.bench_dir, r["image"])
        gt_norm = None
        if r["mask"]:
            gt_norm = gt_bbox_norm(os.path.join(args.bench_dir, r["mask"]))

        if r["image"] in done:
            cached = done[r["image"]]
            findings = _rehydrate(cached["findings"])
            page_dims = tuple(cached["page_dims"])
        else:
            try:
                findings, page_dims = evaluate_image(img_path)
            except Exception as e:
                print(f"  [WARN] fallo en {r['image']}: {e} -> tratada sin hallazgos")
                findings, page_dims = [], (1.0, 1.0)
            raw_out.write(json.dumps({
                "image": r["image"], "doc": r["doc"], "attack": r["attack"],
                "chain": r["chain"], "label": r["label"], "page_dims": page_dims,
                "findings": [{"technique": f.technique, "severity": f.severity.value,
                              "score": f.score, "bbox": f.bbox} for f in findings],
            }) + "\n")
            raw_out.flush()

        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(rows)} muestras evaluadas...")

        for module, techs in MODULE_TECHNIQUES.items():
            page_hit, loc_hit = module_hit(findings, page_dims, techs, gt_norm)
            if r["label"] == "tampered":
                if r["target_module"] == module:
                    key = (module, r["attack"], r["chain"])
                    acc[key]["pos"] += 1
                    acc[key]["page"] += int(page_hit)
                    acc[key]["loc"] += int(loc_hit)
            else:
                key = (module, "clean", r["chain"])
                acc[key]["neg"] += 1
                acc[key]["fp"] += int(page_hit)

    raw_out.close()
    _report(acc, args)


class _F:
    def __init__(self, technique, severity, score, bbox):
        self.technique, self.severity, self.score, self.bbox = technique, _Sev(severity), score, \
            tuple(bbox) if bbox else None


class _Sev:
    def __init__(self, v):
        self.value = v


def _rehydrate(raw):
    return [_F(f["technique"], f["severity"], f["score"], f["bbox"]) for f in raw]


def _report(acc, args):
    # Tabla 1: detección por ataque y cadena (APCER localizado)
    attacks = sorted({k[1] for k in acc if k[1] != "clean"})
    chains = ["none", "recompress", "whatsapp", "print_scan"]

    def _row_for(attack, chain):
        for (m, a, c), v in acc.items():
            if a == attack and c == chain and v["pos"] > 0:
                return v
        return None

    for label, key in (("APCER localizado (IoU>=0.2)", "loc"), ("APCER página (dispara en la página)", "page")):
        print(f"\n========= BENCHMARK v1 — {label}, split={args.split} =========")
        print("(menor = mejor; % de ataques NO detectados por el módulo objetivo)\n")
        print(f"{'ataque':<18}" + "".join(f"{c:<12}" for c in chains))
        for attack in attacks:
            line = f"{attack:<18}"
            for chain in chains:
                row = _row_for(attack, chain)
                if row:
                    apcer = (1 - row[key] / row["pos"]) * 100
                    line += f"{apcer:<12.0f}"
                else:
                    line += f"{'-':<12}"
            print(line)

    print(f"\n========= BPCER por módulo y cadena (falsas alarmas en limpios) =========\n")
    print(f"{'módulo':<14}" + "".join(f"{c:<12}" for c in chains))
    for module in MODULE_TECHNIQUES:
        line = f"{module:<14}"
        for chain in chains:
            v = acc.get((module, "clean", chain))
            if v and v["neg"] > 0:
                line += f"{v['fp'] / v['neg'] * 100:<12.0f}"
            else:
                line += f"{'-':<12}"
        print(line)

    out_json = os.path.join(args.bench_dir, f"metrics_{args.split}.json")
    serializable = {f"{m}|{a}|{c}": v for (m, a, c), v in acc.items()}
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2)
    print(f"\nMétricas guardadas en {out_json}")


if __name__ == "__main__":
    main()
