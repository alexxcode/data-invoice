"""Reproducción de un comando del pipeline experimental de Cotejo (powerUp.md, Fase 4).

Encadena las etapas para que un revisor externo regenere la tabla principal sin
conocer los scripts internos. Cada etapa es idempotente/resume-able: si los
artefactos existen, no se recomputan (salvo --force).

Etapas:
  1. build      genera el benchmark realista (data/benchmark_v1) desde data/hf_eval
  2. classic    evalúa el stack forense clásico (matriz módulo×ataque×cadena)
  3. vlm        evalúa el baseline VLM-as-judge (requiere Gemini; ver --skip-vlm)
  4. fusion     fusión calibrada + ruteo conformal (lee los crudos de 2 y 3)

Ejemplos:
  # todo excepto el VLM (sin coste/llaves), usando cualquier caché VLM presente:
  python reproduce.py --skip-vlm
  # pipeline completo vía Vertex (consume billing GCP):
  VLM_USE_VERTEX=1 GOOGLE_CLOUD_PROJECT=datainvoice python reproduce.py
  # solo recomputar la fusión (etapas 1-3 ya hechas):
  python reproduce.py --only fusion
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
STAGES = ["build", "classic", "vlm", "fusion"]


def run(cmd):
    print(f"\n$ {' '.join(cmd)}\n", flush=True)
    r = subprocess.run(cmd, cwd=REPO)
    if r.returncode != 0:
        print(f"[!] etapa falló (exit {r.returncode}): {' '.join(cmd)}")
        sys.exit(r.returncode)


def exists(*parts):
    return os.path.exists(os.path.join(REPO, *parts))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench_dir", default="data/benchmark_v1")
    ap.add_argument("--base_dir", default="data/hf_eval")
    ap.add_argument("--split", default="test", choices=["all", "calib", "test"])
    ap.add_argument("--prevalence", type=float, default=0.02)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--delta", type=float, default=0.10)
    ap.add_argument("--skip-vlm", action="store_true", help="no llama a Gemini; usa la caché VLM existente")
    ap.add_argument("--only", choices=STAGES, help="corre una sola etapa")
    ap.add_argument("--force", action="store_true", help="recomputa aunque existan artefactos")
    args = ap.parse_args()

    bench = args.bench_dir
    stages = [args.only] if args.only else STAGES

    if "build" in stages:
        if args.force or not exists(bench, "manifest.jsonl"):
            run([PY, "eval/build_benchmark.py", "--base_dir", args.base_dir, "--out_dir", bench])
        else:
            print(f"[=] build: {bench}/manifest.jsonl ya existe (usa --force para regenerar)")

    if "classic" in stages:
        if args.force or not exists(bench, "findings_all.jsonl"):
            run([PY, "eval/eval_benchmark.py", "--bench_dir", bench, "--split", "all"])
        else:
            print(f"[=] classic: findings_all.jsonl ya existe; re-agregando métricas")
            run([PY, "eval/eval_benchmark.py", "--bench_dir", bench, "--split", args.split, "--resume"])

    if "vlm" in stages:
        if args.skip_vlm:
            print("[=] vlm: --skip-vlm activo; se omite el barrido (se usa caché si existe)")
        else:
            run([PY, "eval/eval_vlm.py", "--bench_dir", bench, "--split", args.split, "--sleep", "0.1"])

    if "fusion" in stages:
        run([PY, "eval/fusion_routing.py", "--bench_dir", bench,
             "--alpha", str(args.alpha), "--delta", str(args.delta),
             "--prevalence", str(args.prevalence)])

    print("\n[ok] reproducción completa.")


if __name__ == "__main__":
    main()
