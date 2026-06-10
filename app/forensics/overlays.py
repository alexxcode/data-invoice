import fitz
import os
import cv2
import numpy as np
from typing import List
from .models import ForensicFinding

def generate_overlays(doc: fitz.Document, findings: List[ForensicFinding], output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    
    for i, finding in enumerate(findings):
        if finding.bbox is not None:
            try:
                page = doc[finding.page]
                pix = page.get_pixmap(dpi=150)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                if pix.n >= 3:
                    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                    
                overlay = img.copy()
                scale = 150 / 72.0
                x0, y0, x1, y1 = [int(v * scale) for v in finding.bbox]
                
                # Draw red box
                cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 0, 255), thickness=-1)
                cv2.addWeighted(overlay, 0.45, img, 0.55, 0, img)
                cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 255), thickness=2)
                
                filename = f"overlay_{finding.technique}_{i}.png"
                output_path = os.path.join(output_dir, filename)
                cv2.imwrite(output_path, img)
                
                # Use a relative path or an identifier for the UI
                finding.overlay_path = f"/overlays/{filename}"
            except Exception as e:
                print(f"Failed to generate overlay for {finding.technique}: {e}")
