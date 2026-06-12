"""Evaluación del baseline VLM-as-judge sobre el benchmark v1 (Fase 2).

Misma métrica que el stack clásico (APCER página/localizado, BPCER) para
comparar peras con peras. Las llamadas a Gemini se cachean en JSONL: el barrido
es resume-able y nunca se paga dos veces por la misma imagen.

Uso:
    # smoke barato (n imágenes por categoría, chain=none):
    python eval/eval_vlm.py --bench_dir data/benchmark_v1 --sample 3 --chains none
    # barrido completo del split test (PAGADO):
    python eval/eval_vlm.py --bench_dir data/benchmark_v1 --split test
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.forensics.geometry import compute_iou  # noqa: E402
from eval_benchmark import gt_bbox_norm  # noqa: E402  (reutiliza la misma métrica)
from vlm_judge import DEFAULT_MODEL, judge_image  # noqa: E402

IOU_THRESHOLD = 0.2


def load_cache(path):
    cache = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    cache[r["image"]] = r
                except Exception:
                    pass
    return cache


def select_rows(rows, args):
    if args.split != "all":
        rows = [r for r in rows if r["split"] == args.split]
    if args.chains:
        chains = set(args.chains.split(","))
        rows = [r for r in rows if r["chain"] in chains]
    if args.sample:
        # n por (attack, chain), determinista por orden del manifest
        seen = defaultdict(int)
        picked = []
        for r in rows:
            key = (r["attack"], r["chain"])
            if seen[key] < args.sample:
                seen[key] += 1
                picked.append(r)
        rows = picked
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench_dir", default="data/benchmark_v1")
    ap.add_argument("--split", choices=["all", "calib", "test"], default="test")
    ap.add_argument("--chains", default=None, help="filtra cadenas, ej. 'none,whatsapp'")
    ap.add_argument("--sample", type=int, default=None, help="n por (ataque,cadena) — para smoke barato")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--sleep", type=float, default=0.0, help="segundos entre llamadas (rate limiting)")
    ap.add_argument("--max_calls", type=int, default=None, help="tope de llamadas nuevas por corrida (cuota diaria)")
    args = ap.parse_args()

    manifest = os.path.join(args.bench_dir, "manifest.jsonl")
    rows = [json.loads(l) for l in open(manifest, encoding="utf-8")]
    rows = select_rows(rows, args)

    cache_path = os.path.join(args.bench_dir, f"vlm_{args.model.replace('/', '_')}.jsonl")
    cache = load_cache(cache_path)
    out = open(cache_path, "a", encoding="utf-8")

    acc = defaultdict(lambda: {"pos": 0, "page": 0, "loc": 0, "neg": 0, "fp": 0})
    n_calls = 0
    n_errors = 0
    consecutive_errors = 0
    quota_stop = False

    for i, r in enumerate(rows):
        img_rel = r["image"]
        if img_rel in cache:
            v = cache[img_rel]
        elif quota_stop or (args.max_calls is not None and n_calls >= args.max_calls):
            continue  # sin presupuesto de llamadas: se omite, no se cuenta
        else:
            verdict = judge_image(os.path.join(args.bench_dir, img_rel), model=args.model)
            n_calls += 1
            if verdict.error:
                n_errors += 1
                consecutive_errors += 1
                # 5 errores seguidos (típico: cuota diaria agotada) -> corte limpio
                if consecutive_errors >= 5:
                    print(f"  [!] {consecutive_errors} errores consecutivos; "
                          f"corte temprano. Último: {verdict.error[:120]}")
                    quota_stop = True
                if args.sleep:
                    time.sleep(args.sleep)
                continue  # NO se cachea ni se cuenta en métricas
            consecutive_errors = 0
            v = {
                "image": img_rel, "tampered": verdict.tampered,
                "regions": [list(reg.bbox) for reg in verdict.regions],
                "error": None,
            }
            out.write(json.dumps(v) + "\n")
            out.flush()
            cache[img_rel] = v
            if n_calls % 20 == 0:
                print(f"  {n_calls} llamadas ({n_errors} errores)...")
            if args.sleep:
                time.sleep(args.sleep)

        if v.get("error"):
            continue  # entrada errónea heredada: fuera de métricas

        page_hit = bool(v["tampered"])
        loc_hit = False
        if page_hit and r["mask"]:
            gt = gt_bbox_norm(os.path.join(args.bench_dir, r["mask"]))
            if gt is not None:
                for box in v["regions"]:
                    if compute_iou(tuple(box), gt) >= IOU_THRESHOLD:
                        loc_hit = True
                        break

        if r["label"] == "tampered":
            key = (r["attack"], r["chain"])
            acc[key]["pos"] += 1
            acc[key]["page"] += int(page_hit)
            acc[key]["loc"] += int(loc_hit)
        else:
            key = ("clean", r["chain"])
            acc[key]["neg"] += 1
            acc[key]["fp"] += int(page_hit)

    out.close()
    if n_errors:
        print(f"\n[aviso] {n_errors}/{n_calls} llamadas fallaron (cuota/red). Las métricas "
              f"abajo SOLO cuentan veredictos válidos; faltan muestras por evaluar. "
              f"Reanuda más tarde: el caché conserva lo válido.")
    _report(acc, args, len(rows), n_calls)


def _report(acc, args, n_rows, n_calls):
    attacks = sorted({k[0] for k in acc if k[0] != "clean"})
    chains = sorted({k[1] for k in acc})

    print(f"\n===== VLM-judge ({args.model}) — split={args.split}, muestras={n_rows}, "
          f"llamadas nuevas={n_calls} =====")
    for label, key in (("APCER localizado (IoU>=0.2)", "loc"),
                       ("APCER página (marca el doc como manipulado)", "page")):
        print(f"\n--- {label} (menor mejor) ---")
        print(f"{'ataque':<18}" + "".join(f"{c:<12}" for c in chains))
        for a in attacks:
            line = f"{a:<18}"
            for c in chains:
                v = acc.get((a, c))
                line += (f"{(1 - v[key] / v['pos']) * 100:<12.0f}" if v and v["pos"] else f"{'-':<12}")
            print(line)

    print("\n--- BPCER (marca un limpio como manipulado) ---")
    line = f"{'clean':<18}"
    for c in chains:
        v = acc.get(("clean", c))
        line += (f"{v['fp'] / v['neg'] * 100:<12.0f}" if v and v["neg"] else f"{'-':<12}")
    print(line)

    print("\n--- n evaluado por celda (ataques / limpios por cadena) ---")
    print(f"{'ataque':<18}" + "".join(f"{c:<12}" for c in chains))
    for a in attacks + ["clean"]:
        line = f"{a:<18}"
        for c in chains:
            v = acc.get((a, c))
            n = (v["pos"] if a != "clean" else v["neg"]) if v else 0
            line += f"{n:<12}"
        print(line)

    out_json = os.path.join(args.bench_dir, f"vlm_metrics_{args.split}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({f"{a}|{c}": v for (a, c), v in acc.items()}, f, indent=2)
    print(f"\nMétricas guardadas en {out_json}")


if __name__ == "__main__":
    main()
