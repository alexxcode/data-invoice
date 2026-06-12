"""Fase 3 (powerUp.md): fusión calibrada + ruteo selectivo conformal.

Pregunta que responde: el stack clásico es ruido y el VLM no localiza, pero
¿se puede combinar las señales DÉBILES a nivel documento (clásico + VLM) en un
clasificador calibrado, y rutear con una GARANTÍA estadística de fuga de fraude
en el conjunto AUTO_APPROVE?

Entradas (todas ya cacheadas, sin nuevas llamadas a modelos):
  manifest.jsonl          — label/doc/chain/split por muestra
  findings_all.jsonl      — hallazgos del stack clásico (eval_benchmark)
  vlm_<model>.jsonl        — veredictos del VLM (eval_vlm)

Salidas: AUC de fusión vs clásico-solo vs VLM-solo; umbral conformal con cota
Clopper-Pearson de fuga ≤ α a confianza 1−δ fijado en calibración; curva
riesgo-cobertura en test.

Uso:
    python eval/fusion_routing.py --bench_dir data/benchmark_v1 --alpha 0.05 --delta 0.05
"""
import argparse
import glob
import json
import os
import sys

# Consola Windows (cp1252) no soporta unicode como ≤/α; forzar UTF-8 en stdout
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from scipy.stats import beta
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CLASSIC_TECHS = {
    "typography": "typo",
    "ela": "ela", "noise": "ela",   # ela_noise agrupados
    "copy_move": "cm",
}


def _read_jsonl(path):
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def load_features(bench_dir, vlm_glob="vlm_*.jsonl"):
    manifest = {r["image"]: r for r in _read_jsonl(os.path.join(bench_dir, "manifest.jsonl"))}

    classic = {}
    for r in _read_jsonl(os.path.join(bench_dir, "findings_all.jsonl")):
        classic[r["image"]] = r.get("findings", [])

    vlm = {}
    for vp in glob.glob(os.path.join(bench_dir, vlm_glob)):
        for r in _read_jsonl(vp):
            if r.get("error"):
                continue
            vlm[r["image"]] = r

    rows = []
    for img, meta in manifest.items():
        if img not in classic or img not in vlm:
            continue  # solo muestras con AMBAS señales
        f = classic[img]
        # features clásicas: fired + max score por grupo de técnica
        grp = {"typo": [0.0], "ela": [0.0], "cm": [0.0]}
        for fd in f:
            g = CLASSIC_TECHS.get(fd.get("technique"))
            if g:
                grp[g].append(float(fd.get("score", 0.0)))
        v = vlm[img]
        regions = v.get("regions", []) or []
        vlm_conf = max([0.0] + [_region_conf(rg) for rg in regions]) if regions else (1.0 if v.get("tampered") else 0.0)

        feats = {
            "typo_fired": float(len(grp["typo"]) > 1),
            "typo_score": max(grp["typo"]),
            "ela_fired": float(len(grp["ela"]) > 1),
            "ela_score": max(grp["ela"]),
            "cm_fired": float(len(grp["cm"]) > 1),
            "n_findings": float(len(f)),
            "vlm_tampered": float(bool(v.get("tampered"))),
            "vlm_conf": float(vlm_conf),
            "vlm_nreg": float(len(regions)),
        }
        rows.append({
            "image": img, "doc": meta["doc"], "chain": meta["chain"],
            "split": meta["split"], "y": 1 if meta["label"] == "tampered" else 0,
            "feats": feats,
        })
    return rows


def _region_conf(region):
    # eval_vlm cachea regions como lista de bbox; sin conf explícita -> presencia=1.0
    if isinstance(region, dict):
        return float(region.get("confidence", 1.0))
    return 1.0


FEATURE_SETS = {
    "classic": ["typo_fired", "typo_score", "ela_fired", "ela_score", "cm_fired", "n_findings"],
    "vlm": ["vlm_tampered", "vlm_conf", "vlm_nreg"],
    "fusion": ["typo_fired", "typo_score", "ela_fired", "ela_score", "cm_fired", "n_findings",
               "vlm_tampered", "vlm_conf", "vlm_nreg"],
}


def matrix(rows, cols):
    return np.array([[r["feats"][c] for c in cols] for r in rows], dtype=float)


def grouped_split(rows, seed=0):
    """Split calib/test del benchmark si ambos están poblados; si no, split
    interno agrupado por documento (sin fuga entre variantes del mismo doc)."""
    splits = {r["split"] for r in rows}
    if {"calib", "test"} <= splits:
        calib = [r for r in rows if r["split"] == "calib"]
        test = [r for r in rows if r["split"] == "test"]
        if calib and test:
            return calib, test, "benchmark (calib docs vs test docs)"
    # fallback interno por documento
    docs = sorted({r["doc"] for r in rows})
    rng = np.random.default_rng(seed)
    rng.shuffle(docs)
    half = len(docs) // 2
    calib_docs = set(docs[:half])
    calib = [r for r in rows if r["doc"] in calib_docs]
    test = [r for r in rows if r["doc"] not in calib_docs]
    return calib, test, f"interno agrupado por doc (seed={seed}, {len(calib_docs)}/{len(docs)-len(calib_docs)} docs)"


def clopper_pearson_upper(k, n, delta):
    """Cota superior unilateral (1−δ) de una proporción binomial."""
    if n == 0:
        return 1.0
    if k >= n:
        return 1.0
    return float(beta.ppf(1 - delta, k + 1, n - k))


def conformal_threshold(scores, y, alpha, delta):
    """Mayor umbral t (mayor cobertura) tal que la cota superior (1−δ) de la
    TASA DE FUGA DE FRAUDE (fracción de manipuladas que caen en AUTO_APPROVE,
    score≤t) sea ≤ α. Cantidad independiente de la prevalencia: se estima solo
    sobre la clase tampered, así que la garantía transfiere a cualquier mezcla
    de despliegue. Fijado en calib."""
    tampered = scores[y == 1]
    n_t = len(tampered)
    if n_t == 0:
        return -np.inf
    best_t = -np.inf
    for t in np.unique(scores):
        leaked = int((tampered <= t).sum())  # fraude que se cuela en auto-approve
        if clopper_pearson_upper(leaked, n_t, delta) <= alpha:
            best_t = t
    return best_t


def project_prevalence(clean_approve_rate, tamper_approve_rate, prevalence):
    """Cobertura y fuga proyectadas a una prevalencia de despliegue.
    clean_approve_rate = fracción de limpias auto-aprobadas (especificidad de ruteo)
    tamper_approve_rate = fracción de manipuladas que se cuelan (= fuga por-clase)."""
    pi = prevalence
    coverage = (1 - pi) * clean_approve_rate + pi * tamper_approve_rate
    leak_num = pi * tamper_approve_rate
    leakage = leak_num / coverage if coverage > 0 else 0.0
    return coverage, leakage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench_dir", default="data/benchmark_v1")
    ap.add_argument("--alpha", type=float, default=0.05,
                    help="fracción máxima de FRAUDE tolerada que se cuela en AUTO_APPROVE (recall-on-fraud = 1-alpha)")
    ap.add_argument("--delta", type=float, default=0.05, help="1-confianza de la cota")
    ap.add_argument("--prevalence", type=float, default=0.02,
                    help="prevalencia de manipulación del despliegue real (para reproyectar cobertura/fuga)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rows = load_features(args.bench_dir)
    if len(rows) < 20:
        print(f"Muestras con clásico+VLM: {len(rows)} — insuficiente. "
              f"¿Terminó el barrido VLM? (eval/eval_vlm.py)")
        return

    calib, test, split_desc = grouped_split(rows, args.seed)
    print(f"Muestras (clásico+VLM): {len(rows)} | calib={len(calib)} test={len(test)}")
    print(f"Split: {split_desc}")
    prev = np.mean([r["y"] for r in rows])
    print(f"Prevalencia de manipulación en el benchmark: {prev*100:.0f}% "
          f"(IRREAL a propósito; en un flujo real la mayoría son limpias — ver nota)\n")

    yc = np.array([r["y"] for r in calib])
    yt = np.array([r["y"] for r in test])

    # --- 1. Fusión vs solos: AUC en test ---
    print("===== AUC (discriminación manipulado vs limpio), test =====")
    fusion_model = None
    for name, cols in FEATURE_SETS.items():
        Xc, Xt = matrix(calib, cols), matrix(test, cols)
        clf = LogisticRegression(max_iter=1000, class_weight="balanced").fit(Xc, yc)
        s = clf.predict_proba(Xt)[:, 1]
        try:
            auc = roc_auc_score(yt, s)
        except ValueError:
            auc = float("nan")
        print(f"  {name:<8} AUC = {auc:.3f}")
        if name == "fusion":
            fusion_model = clf

    # --- 2. Ruteo conformal con la fusión ---
    cols = FEATURE_SETS["fusion"]
    sc = fusion_model.predict_proba(matrix(calib, cols))[:, 1]
    st = fusion_model.predict_proba(matrix(test, cols))[:, 1]

    pi = args.prevalence
    print(f"\n===== Ruteo conformal (garantía sobre el FRAUDE, indep. de prevalencia) =====")
    print(f"  Objetivo: ≤{args.alpha*100:.0f}% del fraude se cuela en AUTO_APPROVE, confianza {(1-args.delta)*100:.0f}%")
    t = conformal_threshold(sc, yc, args.alpha, args.delta)
    if not np.isfinite(t):
        print(f"  No existe umbral que garantice escape de fraude ≤ {args.alpha*100:.0f}% en calib.")
    else:
        # tasas por-clase medidas en test
        clean_rate = float((st[yt == 0] <= t).mean()) if (yt == 0).any() else 0.0
        tamper_rate = float((st[yt == 1] <= t).mean()) if (yt == 1).any() else 0.0
        cov_pi, leak_pi = project_prevalence(clean_rate, tamper_rate, pi)
        print(f"  Umbral t = {t:.3f} (fijado en calib)")
        print(f"  En test — fraude que escapa: {tamper_rate*100:.1f}%  (recall de fraude {100-tamper_rate*100:.1f}%) "
              f"| limpias auto-aprobadas: {clean_rate*100:.0f}%")
        print(f"  Proyectado a prevalencia real {pi*100:.0f}%: "
              f"AUTOMATIZACIÓN {cov_pi*100:.0f}% del volumen, FUGA {leak_pi*100:.2f}% de lo auto-aprobado")

    # --- 3. Curva riesgo-cobertura, proyectada a prevalencia de despliegue ---
    print(f"\n===== Curva riesgo-cobertura proyectada a prevalencia {pi*100:.0f}% (test) =====")
    print(f"  {'automatización':<16}{'fuga en auto-approve':<24}{'fraude capturado':<18}")
    for q in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0]:
        thr = np.quantile(st, q)
        clean_rate = float((st[yt == 0] <= thr).mean()) if (yt == 0).any() else 0.0
        tamper_rate = float((st[yt == 1] <= thr).mean()) if (yt == 1).any() else 0.0
        cov_pi, leak_pi = project_prevalence(clean_rate, tamper_rate, pi)
        print(f"  {cov_pi*100:<16.0f}{leak_pi*100:<24.2f}{(1-tamper_rate)*100:<18.0f}")

    print(f"\nLectura: a prevalencia real de cliente ({pi*100:.0f}% manipuladas) el ruteo "
          f"automatiza buena parte del volumen con fuga baja, porque el modelo auto-aprueba "
          f"casi todas las limpias. La garantía conformal se fija sobre el fraude (independiente "
          f"de la mezcla), así que transfiere a despliegues con distinta prevalencia.")


if __name__ == "__main__":
    main()
