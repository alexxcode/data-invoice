import fitz
import re
import cv2
import yaml
import os
import shutil
import numpy as np
import pytesseract
from PIL import Image
from scipy.spatial.distance import mahalanobis
from typing import List
from .models import ForensicFinding, Severity, DocumentClass

OCR_DPI = 300

# Resolución del binario de Tesseract: variable de entorno > PATH > default Windows.
_tess_cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
if not _tess_cmd and os.name == "nt":
    _default_win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_default_win):
        _tess_cmd = _default_win
if _tess_cmd:
    pytesseract.pytesseract.tesseract_cmd = _tess_cmd


def get_stroke_features(crop_gray: np.ndarray):
    # Otsu thresholding
    _, binary = cv2.threshold(crop_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink_area = cv2.countNonZero(binary)

    # Calculate perimeter
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    perimeter = sum(cv2.arcLength(c, True) for c in contours)

    stroke_width = (2 * ink_area / perimeter) if perimeter > 0 else 0
    ink_density = ink_area / (crop_gray.size) if crop_gray.size > 0 else 0
    return stroke_width, ink_density


def regularized_inv_cov(X: np.ndarray) -> np.ndarray:
    """Inversa de covarianza con regularización ridge determinista.

    Sustituye el hack anterior de sumar ruido gaussiano SIN SEMILLA a las
    features (que volvía el detector no determinista: dos corridas sobre el
    mismo documento podían dar findings distintos)."""
    cov = np.cov(X, rowvar=False)
    d = cov.shape[0]
    ridge = max(1e-8, 1e-6 * np.trace(cov) / d)
    return np.linalg.inv(cov + np.eye(d) * ridge)


def analyze_typography(doc: fitz.Document, doc_class: DocumentClass) -> List[ForensicFinding]:
    findings = []
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    typo_config = config.get("typography", {})
    chi2_threshold = typo_config.get("chi2_threshold_995", 14.86)
    high_factor = typo_config.get("high_severity_factor", 2.0)
    digit_regex = re.compile(r'[\d.,]{2,}')

    tokens = []  # List of dicts: {'text', 'bbox' (PDF points), 'features': [], 'page': idx}

    for page_idx, page in enumerate(doc):
        if doc_class in (DocumentClass.NATIVE_DIGITAL, DocumentClass.HYBRID):
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type") == 0:
                    for line in block.get("lines", []):
                        # Line bbox to calculate relative baseline and height
                        line_bbox = line.get("bbox")
                        line_height = line_bbox[3] - line_bbox[1]

                        for span in line.get("spans", []):
                            text = span.get("text", "").strip()
                            if digit_regex.search(text):
                                bbox = span.get("bbox")
                                h = bbox[3] - bbox[1]
                                norm_height = h / line_height if line_height > 0 else 1.0
                                # Posición de la baseline del span dentro de la caja de
                                # línea, normalizada por la altura de línea. span["origin"]
                                # es el origen de baseline en PyMuPDF. (El código anterior
                                # comparaba contra line["dir"], que es el VECTOR DE
                                # DIRECCIÓN de escritura, no una coordenada: feature de ruido.)
                                origin_y = span.get("origin", (0.0, bbox[3]))[1]
                                baseline_offset = (line_bbox[3] - origin_y) / line_height if line_height > 0 else 0.0

                                # Render just this bbox for pixel features
                                try:
                                    pix = page.get_pixmap(clip=bbox, dpi=150)
                                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                                    if pix.n >= 3:
                                        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                                    else:
                                        gray = img
                                    stroke_width, ink_density = get_stroke_features(gray)

                                    features = [norm_height, stroke_width, baseline_offset, ink_density]
                                    tokens.append({"text": text, "bbox": bbox, "features": features, "page": page_idx})
                                except Exception:
                                    pass

        if doc_class in (DocumentClass.SCANNED, DocumentClass.HYBRID) and len(tokens) == 0:
            # Fallback to OCR if no tokens found or explicitly scanned
            pix = page.get_pixmap(dpi=OCR_DPI)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            n_boxes = len(data['text'])

            # Median height per OCR line to normalize token height
            line_heights = {}
            for i in range(n_boxes):
                if data['text'][i].strip() and float(data['conf'][i]) > 0:
                    key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
                    line_heights.setdefault(key, []).append(data['height'][i])
            line_median = {k: float(np.median(v)) for k, v in line_heights.items()}

            # Escala píxeles del render OCR -> puntos PDF (espacio canónico)
            scale = 72.0 / OCR_DPI
            for i in range(n_boxes):
                text = data['text'][i].strip()
                if float(data['conf'][i]) > 60 and digit_regex.search(text):
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    bbox = (x * scale, y * scale, (x + w) * scale, (y + h) * scale)
                    crop = img.crop((x, y, x + w, y + h)).convert("L")
                    gray = np.array(crop)
                    stroke_width, ink_density = get_stroke_features(gray)
                    key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
                    med = line_median.get(key, h)
                    norm_height = h / med if med > 0 else 1.0
                    baseline_offset = 0.0  # baseline no disponible vía Tesseract a este nivel

                    features = [norm_height, stroke_width, baseline_offset, ink_density]
                    tokens.append({"text": text, "bbox": bbox, "features": features, "page": page_idx})

    if len(tokens) > 4:  # Need enough samples for Mahalanobis
        X = np.array([t["features"] for t in tokens])

        try:
            mean = np.mean(X, axis=0)
            inv_cov = regularized_inv_cov(X)

            for t in tokens:
                dist = mahalanobis(t["features"], mean, inv_cov)
                # Mahalanobis distance squared follows Chi-squared distribution
                d2 = dist ** 2
                if d2 > chi2_threshold:
                    severity = Severity.HIGH if d2 > chi2_threshold * high_factor else Severity.MEDIUM
                    findings.append(ForensicFinding(
                        technique="typography",
                        severity=severity,
                        page=t["page"],
                        bbox=t["bbox"],
                        score=min(1.0, d2 / (chi2_threshold * 2)),
                        explanation=f"Inconsistencia tipográfica detectada en el monto '{t['text']}' (Mahalanobis dist^2 = {d2:.2f})."
                    ))
        except Exception as e:
            print(f"Typography covariance error: {e}")

    return findings
