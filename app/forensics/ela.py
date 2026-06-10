import fitz
import io
import yaml
import os
import cv2
import numpy as np
from PIL import Image, ImageChops
from typing import List
from .models import ForensicFinding, Severity, DocumentClass

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
    
    for page_idx, page in enumerate(doc):
        # Extract embedded JPEGs
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                base = doc.extract_image(xref)
                if base["ext"] in ("jpeg", "jpg"):
                    ela_map, (w, h) = run_ela(base["image"])
                    
                    # 1. Normalize
                    p99 = np.percentile(ela_map, 99)
                    if p99 > 0:
                        ela_map = ela_map / p99
                        
                    # 2. Block processing (32x32)
                    block_size = 32
                    h_b, w_b = h // block_size, w // block_size
                    if h_b == 0 or w_b == 0:
                        continue
                        
                    blocks = []
                    for i in range(h_b):
                        for j in range(w_b):
                            block = ela_map[i*block_size:(i+1)*block_size, j*block_size:(j+1)*block_size]
                            blocks.append(block.mean())
                            
                    blocks = np.array(blocks)
                    mean_b = blocks.mean()
                    std_b = blocks.std()
                    
                    if std_b == 0:
                        continue
                        
                    # 3 & 4. Z-score and connected components
                    z_scores = (blocks - mean_b) / std_b
                    anomaly_mask = (z_scores > z_thresh).astype(np.uint8).reshape((h_b, w_b))
                    
                    # 5. Edge filter
                    original = Image.open(io.BytesIO(base["image"])).convert("L")
                    gray = np.array(original)
                    edges = cv2.Canny(gray, 100, 200)
                    kernel = np.ones((5,5), np.uint8)
                    dilated_edges = cv2.dilate(edges, kernel, iterations=1)
                    
                    # Resize edge mask to block size
                    edges_b = cv2.resize(dilated_edges, (w_b, h_b), interpolation=cv2.INTER_AREA)
                    edges_mask = (edges_b > 50).astype(np.uint8)
                    
                    # Only keep anomalies not explained by edges
                    final_mask = cv2.bitwise_and(anomaly_mask, cv2.bitwise_not(edges_mask))
                    
                    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(final_mask, connectivity=8)
                    
                    total_blocks = h_b * w_b
                    
                    for i in range(1, num_labels):
                        area = stats[i, cv2.CC_STAT_AREA]
                        if area / total_blocks > area_thresh:
                            findings.append(ForensicFinding(
                                technique="ela",
                                severity=Severity.MEDIUM,
                                page=page_idx,
                                score=min(1.0, area / (total_blocks * 0.1)),
                                explanation="Región anómala detectada mediante ELA (Error Level Analysis). Posible re-compresión localizada."
                            ))
                            break # Only issue one finding per image to avoid spam
            except Exception as e:
                print(f"Error processing ELA: {e}")
                
    return findings
