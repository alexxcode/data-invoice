"""Inyector de manipulaciones realistas, guiado por OCR (powerUp.md, Fase 1).

Diferencia clave con `tamper_injector.py` (legado): los ataques caen sobre
CONTENIDO REAL (tokens numéricos localizados por OCR), no sobre bloques
aleatorios en posiciones aleatorias. Ningún ataque es "indetectable por
principio" (fondo-sobre-fondo). Cada ataque devuelve la imagen manipulada y
una máscara binaria EXACTA de la región alterada.

Contrato de cada inyector:
    fn(img: PIL.Image, tokens: list[Token], rng: random.Random)
        -> (PIL.Image, mask: np.ndarray | None, info: dict)
    Devuelve (img, None, {"skipped": ...}) si no hay token apto (p. ej. doc sin
    importes detectables). El generador del benchmark trata esos casos como
    "no aplicable", no como negativos.
"""
import os
import random
import re
import shutil
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageDraw, ImageFont

OCR_DPI_NOTE = "las imágenes base ya están a resolución de documento; OCR directo"
DIGIT_RE = re.compile(r"\d")
AMOUNT_RE = re.compile(r"\d[\d.,]*\d|\d")

_tess = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
if not _tess and os.name == "nt":
    _win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_win):
        _tess = _win
if _tess:
    pytesseract.pytesseract.tesseract_cmd = _tess


@dataclass
class Token:
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def box(self):
        return (self.x, self.y, self.x + self.w, self.y + self.h)


def find_numeric_tokens(img: Image.Image, min_conf: int = 50, min_h: int = 10) -> List[Token]:
    """Tokens con al menos un dígito, confianza y altura razonables."""
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    tokens = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        try:
            conf = float(data["conf"][i])
        except ValueError:
            conf = -1
        if conf >= min_conf and DIGIT_RE.search(text) and data["height"][i] >= min_h:
            tokens.append(Token(text, data["left"][i], data["top"][i],
                                data["width"][i], data["height"][i]))
    return tokens


def _empty_mask(img: Image.Image) -> np.ndarray:
    return np.zeros((img.height, img.width), dtype=np.uint8)


def _mask_box(img, box) -> np.ndarray:
    m = _empty_mask(img)
    x0, y0, x1, y1 = [int(v) for v in box]
    m[max(0, y0):y1, max(0, x0):x1] = 1
    return m


def _estimate_ink_color(crop: Image.Image) -> Tuple[int, int, int]:
    """Color medio de los píxeles oscuros (tinta) del crop."""
    arr = np.asarray(crop.convert("RGB")).reshape(-1, 3)
    gray = arr.mean(axis=1)
    thr = np.percentile(gray, 25)
    ink = arr[gray <= thr]
    if len(ink) == 0:
        return (0, 0, 0)
    return tuple(int(v) for v in ink.mean(axis=0))


def _load_font(px_height: int) -> ImageFont.FreeTypeFont:
    # Fuente externa al documento a propósito: simula reescritura con otra herramienta
    candidates = [
        "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "arial.ttf",
        r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf",
    ]
    size = max(8, int(px_height * 1.05))
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _pick(tokens, rng, predicate=None):
    pool = [t for t in tokens if (predicate is None or predicate(t))]
    if not pool:
        return None
    return rng.choice(pool)


# --------------------------------------------------------------------------- #
# Ataques
# --------------------------------------------------------------------------- #

def inject_digit_copy(img, tokens, rng):
    """Copia un dígito de un importe sobre otro dígito del MISMO documento
    (font-matched por construcción). Simula 1.250 -> 1.255 copiando un '5'."""
    img = img.convert("RGB")
    multi = [t for t in tokens if sum(c.isdigit() for c in t.text) >= 2]
    if len(multi) < 1:
        return img, None, {"skipped": "sin token multi-dígito"}
    target = rng.choice(multi)
    # Posición de un dígito dentro del token (aprox. por ancho uniforme)
    n = max(1, len(target.text))
    dw = target.w / n
    # dígito destino dentro del token
    di = rng.randrange(n)
    dst_x = int(target.x + di * dw)
    dst_box = (dst_x, target.y, int(dst_x + dw), target.y + target.h)
    # fuente: un dígito de otro token del doc, mismo tamaño aproximado
    src = _pick(tokens, rng, lambda t: t is not target and t.h > 0)
    if src is None:
        return img, None, {"skipped": "sin token fuente"}
    sn = max(1, len(src.text))
    sdw = src.w / sn
    si = rng.randrange(sn)
    src_x = int(src.x + si * sdw)
    src_crop = img.crop((src_x, src.y, int(src_x + sdw), src.y + src.h))
    src_crop = src_crop.resize((max(1, dst_box[2] - dst_box[0]), target.h))
    img.paste(src_crop, (dst_box[0], dst_box[1]))
    return img, _mask_box(img, dst_box), {"attack": "digit_copy", "token": target.text}


def inject_digit_render(img, tokens, rng):
    """Reescribe un dígito real con una fuente EXTERNA (color/tamaño estimados
    del contexto). Simula edición con un editor de imagen."""
    img = img.convert("RGB")
    target = _pick(tokens, rng, lambda t: sum(c.isdigit() for c in t.text) >= 2)
    if target is None:
        return img, None, {"skipped": "sin token multi-dígito"}
    n = max(1, len(target.text))
    dw = target.w / n
    di = rng.randrange(n)
    dst_x = int(target.x + di * dw)
    dst_box = (dst_x, target.y, int(dst_x + dw), target.y + target.h)
    crop = img.crop(target.box)
    ink = _estimate_ink_color(crop)
    # color de fondo: percentil claro
    arr = np.asarray(crop).reshape(-1, 3)
    bg = tuple(int(v) for v in np.percentile(arr, 85, axis=0))
    draw = ImageDraw.Draw(img)
    draw.rectangle(dst_box, fill=bg)
    new_digit = str(rng.randrange(10))
    font = _load_font(target.h)
    draw.text((dst_box[0], target.y), new_digit, fill=ink, font=font)
    return img, _mask_box(img, dst_box), {"attack": "digit_render", "token": target.text}


def inject_inpaint_erase(img, tokens, rng):
    """Borra un importe completo con inpainting (Telea). Simula eliminar un
    cargo. El detector debe notar la región 'demasiado limpia'."""
    img = img.convert("RGB")
    target = _pick(tokens, rng, lambda t: t.w >= 12 and t.h >= 10)
    if target is None:
        return img, None, {"skipped": "sin token apto"}
    arr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    mask = _mask_box(img, target.box)
    pad = 2
    inpaint_mask = cv2.dilate(mask * 255, np.ones((pad, pad), np.uint8))
    out = cv2.inpaint(arr, inpaint_mask, 3, cv2.INPAINT_TELEA)
    img = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
    return img, mask, {"attack": "inpaint_erase", "token": target.text}


def inject_splice_foreign(img, tokens, rng, foreign_img: Optional[Image.Image] = None,
                          foreign_tokens: Optional[List[Token]] = None):
    """Pega un token numérico de OTRO documento sobre un importe (splicing con
    historial de compresión distinto)."""
    img = img.convert("RGB")
    if foreign_img is None or not foreign_tokens:
        return img, None, {"skipped": "sin documento foráneo"}
    target = _pick(tokens, rng, lambda t: t.w >= 12 and t.h >= 10)
    src = _pick(foreign_tokens, rng, lambda t: t.w >= 8 and t.h >= 8)
    if target is None or src is None:
        return img, None, {"skipped": "sin par apto"}
    src_crop = foreign_img.convert("RGB").crop(src.box).resize((target.w, target.h))
    img.paste(src_crop, (target.x, target.y))
    return img, _mask_box(img, target.box), {"attack": "splice_foreign", "token": target.text}


def inject_copy_move_region(img, tokens, rng):
    """Clona una banda de una línea de texto sobre otra zona (copy-move rígido
    con desplazamiento coherente). Cubre un cargo con fondo+texto de otra línea."""
    img = img.convert("RGB")
    w, h = img.size
    if not tokens:
        return img, None, {"skipped": "sin tokens"}
    t = rng.choice(tokens)
    band_h = max(16, t.h + 8)
    band_w = int(min(w * 0.45, max(t.w * 3, 120)))
    sx = max(0, min(w - band_w, t.x - 10))
    sy = max(0, min(h - band_h, t.y - 4))
    crop = img.crop((sx, sy, sx + band_w, sy + band_h))
    # destino desplazado verticalmente al menos 2*band_h, dentro de la página
    options = [dy for dy in range(2 * band_h, h - band_h, band_h)]
    if not options:
        return img, None, {"skipped": "página corta"}
    dy = rng.choice(options)
    dst_y = sy + dy if sy + dy + band_h <= h else max(0, sy - dy)
    img.paste(crop, (sx, dst_y))
    return img, _mask_box(img, (sx, dst_y, sx + band_w, dst_y + band_h)), \
        {"attack": "copy_move_region", "shift": (0, dst_y - sy)}


def make_clean(img, tokens, rng):
    """Negativo: sin manipulación (la cadena de transmisión se aplica aparte)."""
    return img.convert("RGB"), None, {"attack": "clean"}


ATTACKS = {
    "digit_copy": inject_digit_copy,
    "digit_render": inject_digit_render,
    "inpaint_erase": inject_inpaint_erase,
    "splice_foreign": inject_splice_foreign,
    "copy_move_region": inject_copy_move_region,
}

# Qué módulo forense debería detectar cada ataque (para la matriz de evaluación)
ATTACK_TARGET_MODULE = {
    "digit_copy": "copy_move",
    "digit_render": "typography",
    "inpaint_erase": "ela_noise",
    "splice_foreign": "ela_noise",
    "copy_move_region": "copy_move",
}
