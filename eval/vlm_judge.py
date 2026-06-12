"""Baseline VLM-as-judge forense (powerUp.md, Fase 2, Pilar B).

Usa Gemini como detector de manipulación: por cada imagen pregunta si el
documento fue alterado y, de serlo, dónde (bounding boxes normalizados). La
salida se normaliza al mismo contrato que los detectores clásicos para poder
medirla con la misma métrica IoU/APCER/BPCER del benchmark.

Punto de comparación honesto: a diferencia del stack clásico (que no localiza
nada, ver powerUp.md §5 Fase 1), aquí medimos si un modelo multimodal de
propósito general localiza fraude en facturas reales sin entrenamiento.
"""
import io
import json
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image

# Reutiliza el cliente lazy del pipeline (no exige API key al importar)
from app.extraction import get_client

DEFAULT_MODEL = os.environ.get("VLM_JUDGE_MODEL", "gemini-2.5-flash")

_PROMPT = (
    "Eres un perito forense de documentos. Analizas la imagen de UNA factura/recibo "
    "y decides si fue manipulada digitalmente (un importe reescrito, un dígito copiado, "
    "una línea borrada con relleno, una región clonada o un fragmento pegado de otro "
    "documento).\n\n"
    "Responde SOLO con JSON válido con esta forma exacta:\n"
    "{\n"
    '  "tampered": true|false,\n'
    '  "regions": [\n'
    '    {"bbox": [x0, y0, x1, y1], "confidence": 0.0-1.0, "reason": "texto breve"}\n'
    "  ]\n"
    "}\n\n"
    "Las coordenadas del bbox son FRACCIONES del ancho/alto de la imagen en [0,1] "
    "(esquina superior izquierda = [0,0]). Si no hay manipulación, devuelve "
    '"tampered": false y "regions": []. No expliques fuera del JSON. '
    "No marques como manipulación el ruido natural de escaneo, la compresión JPEG, "
    "el desenfoque ni los logotipos legítimos.\n"
    "Sé específico: una región por manipulación, lo más ajustada posible al área alterada."
)


@dataclass
class VLMRegion:
    bbox: Tuple[float, float, float, float]  # normalizado [0,1]
    confidence: float
    reason: str


@dataclass
class VLMVerdict:
    tampered: bool
    regions: List[VLMRegion]
    raw: str = ""
    error: Optional[str] = None


def _clamp01(v: float) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    # Tolera modelos que devuelven 0-1000 o 0-100 en vez de 0-1
    if v > 1.0:
        v = v / 1000.0 if v > 100 else v / 100.0
    return max(0.0, min(1.0, v))


def _parse_regions(data) -> List[VLMRegion]:
    regions = []
    for r in data.get("regions", []) or []:
        box = r.get("bbox") or r.get("box")
        if not box or len(box) != 4:
            continue
        x0, y0, x1, y1 = (_clamp01(box[0]), _clamp01(box[1]), _clamp01(box[2]), _clamp01(box[3]))
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        regions.append(VLMRegion(
            bbox=(x0, y0, x1, y1),
            confidence=_clamp01(r.get("confidence", 0.5)),
            reason=str(r.get("reason", ""))[:200],
        ))
    return regions


def judge_image(path: str, model: str = DEFAULT_MODEL) -> VLMVerdict:
    """Envía una imagen a Gemini y devuelve su veredicto forense estructurado."""
    from google.genai import types

    img = Image.open(path).convert("RGB")
    # Acota el tamaño para controlar coste/latencia sin perder legibilidad
    img.thumbnail((1600, 1600))

    try:
        response = get_client().models.generate_content(
            model=model,
            contents=[img, _PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
        text = response.text or ""
        data = json.loads(text)
        return VLMVerdict(
            tampered=bool(data.get("tampered", False)),
            regions=_parse_regions(data),
            raw=text,
        )
    except Exception as e:
        return VLMVerdict(tampered=False, regions=[], error=str(e))


if __name__ == "__main__":
    import sys
    v = judge_image(sys.argv[1])
    print(json.dumps({
        "tampered": v.tampered,
        "regions": [{"bbox": r.bbox, "confidence": r.confidence, "reason": r.reason} for r in v.regions],
        "error": v.error,
    }, indent=2, ensure_ascii=False))
