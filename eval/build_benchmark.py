"""Generador del benchmark realista v1 (powerUp.md, Fase 1).

Grid: documento base × ataque × cadena de transmisión.
- Ataques realistas guiados por OCR (realistic_injector).
- Cada variante manipulada se somete a cada cadena de transmisión
  (transmission), transformando la máscara GT en paralelo.
- Negativos limpios: un clean por documento por cadena (mismos negativos
  duros, para medir BPCER bajo cada condición de transmisión).
- Split calib/test por paridad del índice de documento (determinista).
- Manifest JSONL: una fila por muestra evaluable.

Uso:
    python eval/build_benchmark.py --base_dir data/hf_eval --out_dir data/benchmark_v1
"""
import argparse
import json
import os
import random
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from realistic_injector import (  # noqa: E402
    ATTACKS, ATTACK_TARGET_MODULE, find_numeric_tokens, inject_splice_foreign, make_clean,
)
from transmission import CHAINS, apply_chain  # noqa: E402


def base_doc_indices(base_dir):
    import re
    pat = re.compile(r"doc_(\d+)_base\.jpg$")
    idx = sorted(int(pat.match(f).group(1)) for f in os.listdir(base_dir) if pat.match(f))
    return idx


def save_mask(mask, path):
    Image.fromarray((mask > 0).astype(np.uint8) * 255).save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base_dir", default="data/hf_eval")
    ap.add_argument("--out_dir", default="data/benchmark_v1")
    ap.add_argument("--limit", type=int, default=None, help="máx. documentos (debug)")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    img_dir = os.path.join(args.out_dir, "images")
    mask_dir = os.path.join(args.out_dir, "masks")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(mask_dir, exist_ok=True)

    indices = base_doc_indices(args.base_dir)
    if args.limit:
        indices = indices[: args.limit]

    # OCR de cada documento una sola vez (caché de tokens)
    docs = {}
    for di in indices:
        path = os.path.join(args.base_dir, f"doc_{di}_base.jpg")
        img = Image.open(path).convert("RGB")
        docs[di] = {"img": img, "tokens": find_numeric_tokens(img)}
        print(f"OCR doc {di}: {len(docs[di]['tokens'])} tokens numéricos")

    manifest_path = os.path.join(args.out_dir, "manifest.jsonl")
    n_rows = 0
    skipped = 0
    with open(manifest_path, "w", encoding="utf-8") as mf:
        for di in indices:
            base_img = docs[di]["img"]
            tokens = docs[di]["tokens"]
            split = "calib" if di % 2 == 0 else "test"
            # documento foráneo para splice = siguiente índice (circular)
            foreign_di = indices[(indices.index(di) + 1) % len(indices)]
            foreign = docs[foreign_di]

            # 1) Variantes manipuladas (una inyección por ataque, máscara base)
            variants = []  # (attack, img, mask, target_module)
            for attack, fn in ATTACKS.items():
                rng = random.Random(f"bench-{di}-{attack}")
                if attack == "splice_foreign":
                    out, mask, info = inject_splice_foreign(
                        base_img, tokens, rng, foreign["img"], foreign["tokens"])
                else:
                    out, mask, info = fn(base_img, tokens, rng)
                if mask is None:
                    skipped += 1
                    continue
                variants.append((attack, out, mask, ATTACK_TARGET_MODULE[attack]))

            # 2) Negativo limpio (sin manipular)
            clean_img, _, _ = make_clean(base_img, tokens, random.Random(f"bench-{di}-clean"))
            variants.append(("clean", clean_img, None, None))

            # 3) Cada variante × cada cadena de transmisión
            for attack, var_img, var_mask, target in variants:
                for chain in CHAINS:
                    rng = random.Random(f"bench-{di}-{attack}-{chain}")
                    ti, tm = apply_chain(var_img, var_mask, chain, rng)
                    stem = f"doc{di}_{attack}_{chain}"
                    img_path = os.path.join(img_dir, stem + ".jpg")
                    ti.save(img_path, "JPEG", quality=92)
                    mask_path = None
                    if tm is not None:
                        mask_path = os.path.join(mask_dir, stem + ".png")
                        save_mask(tm, mask_path)
                    row = {
                        "doc": di, "attack": attack, "chain": chain,
                        "label": "clean" if attack == "clean" else "tampered",
                        "target_module": target, "split": split,
                        "image": os.path.relpath(img_path, args.out_dir),
                        "mask": os.path.relpath(mask_path, args.out_dir) if mask_path else None,
                    }
                    mf.write(json.dumps(row) + "\n")
                    n_rows += 1

    print(f"\nBenchmark v1 generado: {n_rows} muestras en {args.out_dir}")
    print(f"Inyecciones omitidas (sin token apto): {skipped}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
