import fitz
import os
import yaml
import cv2
import numpy as np
from sklearn.cluster import DBSCAN
from typing import List
from .models import ForensicFinding, Severity, DocumentClass

def get_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def analyze_copy_move(doc: fitz.Document, doc_class: DocumentClass) -> List[ForensicFinding]:
    findings = []
    # Can apply to any class but NATIVE_DIGITAL may yield FP if not careful
    if doc_class == DocumentClass.NATIVE_DIGITAL:
        return findings
        
    config = get_config()
    cm_config = config.get("copy_move", {})
    eps = cm_config.get("dbscan_eps", 8)
    min_samples = cm_config.get("dbscan_min_samples", 6)
    ratio_test = cm_config.get("ratio_test", 0.75)
    
    # Use AKAZE for text
    akaze = cv2.AKAZE_create()
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    
    for page_idx, page in enumerate(doc):
        try:
            pix = page.get_pixmap(dpi=150)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n >= 3:
                gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            else:
                gray = img
                
            kp, des = akaze.detectAndCompute(gray, None)
            
            if des is None or len(kp) < 10:
                continue
                
            # Match against itself
            # k=2 because the closest match will be the keypoint itself
            matches = bf.knnMatch(des, des, k=2)
            
            good_matches = []
            displacements = []
            h, w = gray.shape
            
            for m, n in matches:
                if m.distance < ratio_test * n.distance:
                    pt1 = np.array(kp[m.queryIdx].pt)
                    pt2 = np.array(kp[m.trainIdx].pt)
                    
                    # Ignore self-match and very close matches
                    spatial_dist = np.linalg.norm(pt1 - pt2)
                    if spatial_dist > 40:
                        # Top 15% filter (ignore logos)
                        if pt1[1] < h * 0.15 and pt2[1] < h * 0.15:
                            continue
                            
                        # Displacement vector
                        disp = pt2 - pt1
                        # We only want one direction of the symmetric match
                        if disp[0] < 0 or (disp[0] == 0 and disp[1] < 0):
                            disp = -disp
                            
                        good_matches.append((pt1, pt2))
                        displacements.append(disp)
                        
            if not displacements:
                continue
                
            displacements = np.array(displacements)
            clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(displacements)
            
            labels = clustering.labels_
            unique_labels = set(labels)
            
            for label in unique_labels:
                if label == -1:
                    continue
                    
                cluster_mask = (labels == label)
                cluster_disps = displacements[cluster_mask]
                
                # Exclude matches if they don't form a coherent rigid translation
                # Text naturally repeats, but rigid copy-move produces identical displacements (+- 2px)
                mean_disp = cluster_disps.mean(axis=0)
                coherent = np.all(np.abs(cluster_disps - mean_disp) <= 2, axis=1)
                
                if np.sum(coherent) >= min_samples:
                    # Found a cloned region
                    cluster_pts1 = np.array([good_matches[i][0] for i, mask in enumerate(cluster_mask) if mask])
                    cluster_pts2 = np.array([good_matches[i][1] for i, mask in enumerate(cluster_mask) if mask])
                    
                    # Bounding boxes
                    x1, y1 = cluster_pts1.min(axis=0)
                    x2, y2 = cluster_pts1.max(axis=0)
                    bbox1 = (x1, y1, x2, y2)
                    
                    x1_2, y1_2 = cluster_pts2.min(axis=0)
                    x2_2, y2_2 = cluster_pts2.max(axis=0)
                    bbox2 = (x1_2, y1_2, x2_2, y2_2)
                    
                    # Compute union bbox for the finding overlay
                    overall_bbox = (
                        min(bbox1[0], bbox2[0]),
                        min(bbox1[1], bbox2[1]),
                        max(bbox1[2], bbox2[2]),
                        max(bbox1[3], bbox2[3])
                    )
                    
                    findings.append(ForensicFinding(
                        technique="copy_move",
                        severity=Severity.MEDIUM,
                        page=page_idx,
                        bbox=overall_bbox,
                        score=min(1.0, np.sum(coherent) / 20.0),
                        explanation=f"Región clonada detectada ({np.sum(coherent)} keypoints). Desplazamiento coherente."
                    ))
                    
        except Exception as e:
            print(f"Error in copy-move analysis: {e}")
            
    return findings
