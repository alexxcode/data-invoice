"""Cadenas de transmisión realistas para el benchmark (powerUp.md, Fase 1).

Cada cadena simula lo que le ocurre a una factura entre la manipulación y la
recepción por el auditor. Es la dimensión experimental central: un detector
que solo funciona en `none` no sirve en producción.

Las operaciones geométricas (resize, rotación) se aplican IDÉNTICAMENTE a la
máscara ground-truth para que la métrica de localización siga siendo válida.
"""
import io
import random
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def _jpeg_roundtrip(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _resize_mask(mask: Optional[np.ndarray], size: Tuple[int, int]) -> Optional[np.ndarray]:
    if mask is None:
        return None
    m = Image.fromarray((mask > 0).astype(np.uint8) * 255)
    m = m.resize(size, Image.NEAREST)
    return (np.array(m) > 0).astype(np.uint8)


def chain_none(img, mask, rng):
    return img, mask


def chain_recompress(img, mask, rng):
    """Recompresión JPEG con calidad aleatoria (reenvío por email/gestor doc)."""
    q = rng.randint(60, 85)
    return _jpeg_roundtrip(img, q), mask


def chain_whatsapp(img, mask, rng):
    """Aproximación al pipeline de WhatsApp: lado mayor ~1280px y q~70."""
    w, h = img.size
    long_side = max(w, h)
    if long_side > 1280:
        scale = 1280 / long_side
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        img = img.resize(new_size, Image.LANCZOS)
        mask = _resize_mask(mask, new_size)
    return _jpeg_roundtrip(img, 70), mask


def chain_print_scan(img, mask, rng):
    """Simulación de imprimir y re-escanear: rotación leve, blur, ruido de
    sensor, jitter de brillo/contraste y recompresión."""
    angle = rng.uniform(-0.6, 0.6)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))
    if mask is not None:
        m = Image.fromarray((mask > 0).astype(np.uint8) * 255)
        m = m.rotate(angle, resample=Image.NEAREST, expand=False, fillcolor=0)
        mask = (np.array(m) > 0).astype(np.uint8)

    img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 0.8)))

    arr = np.asarray(img).astype(np.float32)
    noise = np.random.default_rng(rng.randint(0, 2**31)).normal(0, rng.uniform(1.5, 3.0), arr.shape)
    img = Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))

    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.97, 1.03))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.95, 1.05))
    return _jpeg_roundtrip(img, 85), mask


CHAINS = {
    "none": chain_none,
    "recompress": chain_recompress,
    "whatsapp": chain_whatsapp,
    "print_scan": chain_print_scan,
}


def apply_chain(img: Image.Image, mask: Optional[np.ndarray], chain: str,
                rng: random.Random) -> Tuple[Image.Image, Optional[np.ndarray]]:
    """Aplica una cadena a la imagen y (si existe) a su máscara GT."""
    return CHAINS[chain](img.convert("RGB"), mask, rng)
