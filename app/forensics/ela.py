import fitz
import io
import yaml
import os
import cv2
import numpy as np
from PIL import Image, ImageChops
from typing import List
from .models import ForensicFinding, Severity, DocumentClass
from .geometry import image_bbox_to_page_points


def get_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_ela(jpeg_bytes: bytes, quality: int = 90) -> np.ndarray:
    original = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    buf = io.BytesIO()
    original.save(buf, "JPEG", quality=quality)
    recompressed = Image.open(buf)
    diff = ImageChops.difference(original, recompressed)
    ela = np.asarray(diff).astype(np.float32).max(axis=2)
    return ela, original.size


def analyze_ela(doc: fitz.Document, doc_class: DocumentClass) -> List[ForensicFinding]:
    findings = []
    if doc_class == DocumentClass.NATIVE_DIGITAL:
        return findings

    config = get_config()
    ela_config = config.get("ela", {})
    z_thresh = ela_config.get("z_score_threshold", 3.0)
    area_thresh = ela_config.get("area_threshold_pct", 0.001)
    use_edge_filter = ela_config.get("edge_filter", True)

    block_size = 32

    for page_idx, page in enumerate(doc):
        # Extract embedded JPEGs
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                base = doc.extract_image(xref)
                if base["ext"] not in ("jpeg", "jpg"):
                    continue
                ela_map, (w, h) = run_ela(base["image"])

                # 1. Normalize
                p99 = np.percentile(ela_map, 99)
                if p99 > 0:
                    ela_map = ela_map / p99

                # 2. Block processing (32x32)
                h_b, w_b = h // block_size, w // block_size
                if h_b == 0 or w_b == 0:
                    continue

                block_means = np.zeros((h_b, w_b))
                for i in range(h_b):
                    for j in range(w_b):
                        block = ela_map[i * block_size:(i + 1) * block_size,
                                        j * block_size:(j + 1) * block_size]
                        block_means[i, j] = block.mean()

                mean_b = block_means.mean()
                std_b = block_means.std()
                if std_b == 0:
                    continue

                # 3 & 4. Z-score and connected components
                z_scores = (block_means - mean_b) / std_b
                anomaly_mask = (z_scores > z_thresh).astype(np.uint8)

                # 5. Edge filter (spec §4.5): el texto negro sobre blanco genera ELA
                # alto de forma natural; solo cuentan bloques anómalos cuya energía
                # no se explica por bordes de alto contraste. (Estuvo desactivado
                # durante la evaluación sintética — ver powerUp.md §1.2.)
                if use_edge_filter:
                    original = Image.open(io.BytesIO(base["image"])).convert("L")
                    gray = np.array(original)
                    edges = cv2.Canny(gray, 100, 200)
                    kernel = np.ones((5, 5), np.uint8)
                    dilated_edges = cv2.dilate(edges, kernel, iterations=1)
                    edges_b = cv2.resize(dilated_edges, (w_b, h_b), interpolation=cv2.INTER_AREA)
                    edges_mask = (edges_b > 50).astype(np.uint8)
                    final_mask = (anomaly_mask * (1 - edges_mask)).astype(np.uint8)
                else:
                    final_mask = anomaly_mask

                num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(final_mask, connectivity=8)

                total_blocks = h_b * w_b

                # Mayor componente que supere el umbral de área -> un finding por imagen
                best = None
                for i in range(1, num_labels):
                    area = stats[i, cv2.CC_STAT_AREA]
                    if area / total_blocks > area_thresh and (best is None or area > stats[best, cv2.CC_STAT_AREA]):
                        best = i

                if best is not None:
                    area = stats[best, cv2.CC_STAT_AREA]
                    # bbox del componente: bloques -> píxeles de imagen -> puntos de página
                    bx = stats[best, cv2.CC_STAT_LEFT]
                    by = stats[best, cv2.CC_STAT_TOP]
                    bw = stats[best, cv2.CC_STAT_WIDTH]
                    bh = stats[best, cv2.CC_STAT_HEIGHT]
                    bbox_img_px = (bx * block_size, by * block_size,
                                   (bx + bw) * block_size, (by + bh) * block_size)
                    bbox = image_bbox_to_page_points(page, xref, bbox_img_px, w, h)

                    findings.append(ForensicFinding(
                        technique="ela",
                        severity=Severity.MEDIUM,
                        page=page_idx,
                        bbox=bbox,
                        score=min(1.0, area / (total_blocks * 0.1)),
                        explanation="Región anómala detectada mediante ELA (Error Level Analysis). Posible re-compresión localizada."
                    ))
            except Exception as e:
                print(f"Error processing ELA: {e}")

    return findings
