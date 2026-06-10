import fitz
import re
import cv2
import yaml
import os
import numpy as np
import pytesseract
from PIL import Image
from scipy.spatial.distance import mahalanobis
from scipy.linalg import inv
from typing import List
from .models import ForensicFinding, Severity, DocumentClass

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

def analyze_typography(doc: fitz.Document, doc_class: DocumentClass) -> List[ForensicFinding]:
    findings = []
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    chi2_threshold = config.get("typography", {}).get("chi2_threshold_995", 14.86)
    digit_regex = re.compile(r'[\d.,]{2,}')
    
    tokens = [] # List of dicts: {'text', 'bbox', 'features': [], 'page': idx}
    
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
                                baseline_offset = abs(span.get("origin", (0,0))[1] - line.get("dir", (0,0))[1]) # Approximation
                                
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
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            n_boxes = len(data['text'])
            
            # Simple line height estimation by grouping by block/par/line
            for i in range(n_boxes):
                text = data['text'][i].strip()
                if int(data['conf'][i]) > 60 and digit_regex.search(text):
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    bbox = (x/2, y/2, (x+w)/2, (y+h)/2) # Adjust for 300 vs 150 dpi coordinate space (fitz is 72 dpi actually, but we scale)
                    # Simplified features for OCR
                    crop = img.crop((x, y, x+w, y+h)).convert("L")
                    gray = np.array(crop)
                    stroke_width, ink_density = get_stroke_features(gray)
                    norm_height = 1.0 # Cannot easily compute line median here without more logic
                    baseline_offset = 0.0
                    
                    features = [norm_height, stroke_width, baseline_offset, ink_density]
                    tokens.append({"text": text, "bbox": bbox, "features": features, "page": page_idx})

    if len(tokens) > 4: # Need enough samples for Mahalanobis
        X = np.array([t["features"] for t in tokens])
        # Add small noise to avoid singular matrix
        X += np.random.normal(0, 1e-5, X.shape)
        
        try:
            mean = np.mean(X, axis=0)
            cov = np.cov(X, rowvar=False)
            inv_cov = inv(cov)
            
            for t in tokens:
                dist = mahalanobis(t["features"], mean, inv_cov)
                # Mahalanobis distance squared follows Chi-squared distribution
                if dist**2 > chi2_threshold:
                    findings.append(ForensicFinding(
                        technique="typography",
                        severity=Severity.HIGH,
                        page=t["page"],
                        bbox=t["bbox"],
                        score=min(1.0, (dist**2) / (chi2_threshold * 2)),
                        explanation=f"Inconsistencia tipográfica detectada en el monto '{t['text']}' (Mahalanobis dist^2 = {dist**2:.2f})."
                    ))
        except Exception as e:
            print(f"Typography covariance error: {e}")
            
    return findings
