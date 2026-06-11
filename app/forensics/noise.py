import fitz
import yaml
import os
import cv2
import numpy as np
from skimage.restoration import denoise_wavelet
from typing import List
from .models import ForensicFinding, Severity, DocumentClass
from .geometry import pixels_to_points

RENDER_DPI = 150

def get_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def noise_map(gray: np.ndarray, block: int = 64) -> np.ndarray:
    den = denoise_wavelet(gray, channel_axis=None, rescale_sigma=True)
    residual = gray.astype(np.float32) - den.astype(np.float32)
    h, w = residual.shape
    out = np.zeros((h // block, w // block))
    for i in range(out.shape[0]):
        for j in range(out.shape[1]):
            out[i, j] = residual[i*block:(i+1)*block, j*block:(j+1)*block].std()
    return out

def analyze_noise(doc: fitz.Document, doc_class: DocumentClass) -> List[ForensicFinding]:
    findings = []
    if doc_class == DocumentClass.NATIVE_DIGITAL:
        return findings
        
    config = get_config()
    noise_config = config.get("noise", {})
    z_thresh = noise_config.get("z_score_threshold", 3.0)
    area_thresh = noise_config.get("area_threshold_pct", 0.001)
    
    for page_idx, page in enumerate(doc):
        try:
            pix = page.get_pixmap(dpi=RENDER_DPI)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n >= 3:
                gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            else:
                gray = img
                
            block_size = 64
            n_map = noise_map(gray, block=block_size)
            h_b, w_b = n_map.shape
            
            if h_b == 0 or w_b == 0:
                continue
                
            mean_b = n_map.mean()
            std_b = n_map.std()
            
            if std_b == 0:
                continue
                
            z_scores = (n_map - mean_b) / std_b
            anomaly_mask = (z_scores > z_thresh).astype(np.uint8)
            
            # Edge filter
            edges = cv2.Canny(gray, 100, 200)
            kernel = np.ones((5,5), np.uint8)
            dilated_edges = cv2.dilate(edges, kernel, iterations=1)
            edges_b = cv2.resize(dilated_edges, (w_b, h_b), interpolation=cv2.INTER_AREA)
            edges_mask = (edges_b > 50).astype(np.uint8)
            
            final_mask = cv2.bitwise_and(anomaly_mask, cv2.bitwise_not(edges_mask))
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(final_mask, connectivity=8)
            total_blocks = h_b * w_b
            
            # Mayor componente que supere el umbral de área -> un finding por página
            best = None
            for i in range(1, num_labels):
                area = stats[i, cv2.CC_STAT_AREA]
                if area / total_blocks > area_thresh and (best is None or area > stats[best, cv2.CC_STAT_AREA]):
                    best = i

            if best is not None:
                area = stats[best, cv2.CC_STAT_AREA]
                # bbox: bloques -> píxeles del render -> puntos PDF (espacio canónico)
                bx = stats[best, cv2.CC_STAT_LEFT]
                by = stats[best, cv2.CC_STAT_TOP]
                bw = stats[best, cv2.CC_STAT_WIDTH]
                bh = stats[best, cv2.CC_STAT_HEIGHT]
                bbox_px = (bx * block_size, by * block_size,
                           (bx + bw) * block_size, (by + bh) * block_size)
                bbox = pixels_to_points(bbox_px, RENDER_DPI)

                findings.append(ForensicFinding(
                    technique="noise",
                    severity=Severity.MEDIUM,
                    page=page_idx,
                    bbox=bbox,
                    score=min(1.0, area / (total_blocks * 0.1)),
                    explanation="Inconsistencia de ruido local (wavelet residual). Posible parcheado."
                ))
        except Exception as e:
            print(f"Error processing Noise analysis: {e}")

    return findings
