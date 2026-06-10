import os
import argparse
from datasets import load_dataset
from PIL import Image

# Import the inject functions from our tamper_injector
from tamper_injector import (
    create_hard_negative,
    inject_region_patch,
    inject_digit_swap,
    inject_clone_region
)
from app.forensics.models import DocumentClass
from app.forensics.classifier import classify_document
from app.forensics.ela import analyze_ela
from app.forensics.noise import analyze_noise
from app.forensics.copy_move import analyze_copy_move
from app.forensics.typography import analyze_typography
import fitz

def evaluate_document(file_path):
    doc = fitz.open(file_path)
    doc_class = classify_document(doc)
    findings = []
    findings.extend(analyze_typography(doc, doc_class))
    findings.extend(analyze_copy_move(doc, doc_class))
    findings.extend(analyze_ela(doc, doc_class))
    findings.extend(analyze_noise(doc, doc_class))
    return findings

def evaluate_hf_batch(batch_size=10, start_idx=0):
    print(f"Loading HuggingFace dataset in streaming mode...")
    dataset = load_dataset("mychen76/invoices-and-receipts_ocr_v1", split="train", streaming=True)
    
    # Iterator to skip and fetch
    iterator = iter(dataset)
    for _ in range(start_idx):
        try:
            next(iterator)
        except StopIteration:
            print("Reached end of dataset during skip.")
            return
            
    out_dir = os.path.join("data", "hf_eval")
    os.makedirs(out_dir, exist_ok=True)
    
    stats = {
        "typography": {"tp": 0, "tn": 0, "fp": 0, "fn": 0},
        "ela_noise": {"tp": 0, "tn": 0, "fp": 0, "fn": 0},
        "copy_move": {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    }
    
    docs_processed = 0
    for i in range(batch_size):
        try:
            item = next(iterator)
        except StopIteration:
            break
            
        print(f"\n--- Processing HF Document {start_idx + i} ---")
        img = item["image"].convert("RGB")
        
        # Save base image to disk (needed by inject functions and evaluator)
        base_path = os.path.join(out_dir, f"doc_{start_idx + i}_base.jpg")
        img.save(base_path, "JPEG", quality=95)
        
        test_cases = []
        
        # 1. Clean
        p_clean, t_clean, m_clean = create_hard_negative(base_path, os.path.join(out_dir, f"doc_{start_idx + i}_clean.jpg"))
        test_cases.append((p_clean, m_clean, "clean"))
        
        # 2. Region Patch (for ELA/Noise)
        p_patch, t_patch, m_patch = inject_region_patch(base_path, os.path.join(out_dir, f"doc_{start_idx + i}_patch.jpg"), os.path.join(out_dir, f"doc_{start_idx + i}_patch_mask.png"))
        test_cases.append((p_patch, m_patch, "tampered"))
        
        # 3. Digit Swap (for Typography)
        p_swap, t_swap, m_swap = inject_digit_swap(base_path, os.path.join(out_dir, f"doc_{start_idx + i}_swap.jpg"), os.path.join(out_dir, f"doc_{start_idx + i}_swap_mask.png"))
        test_cases.append((p_swap, m_swap, "tampered"))
        
        # 4. Clone Region (for Copy-Move)
        p_clone, t_clone, m_clone = inject_clone_region(base_path, os.path.join(out_dir, f"doc_{start_idx + i}_clone.jpg"), os.path.join(out_dir, f"doc_{start_idx + i}_clone_mask.png"))
        test_cases.append((p_clone, m_clone, "tampered"))
        
        # Evaluate each case
        for img_path, mask_path, ground_truth_class in test_cases:
            print(f"Evaluating {img_path}...")
            findings = evaluate_document(img_path)
            
            found_modules = set([f.technique for f in findings])
            is_tampered = (ground_truth_class == "tampered")
            
            for mod in stats.keys():
                if mod == "ela_noise":
                    detected = "ela" in found_modules or "noise" in found_modules
                else:
                    detected = mod in found_modules
                
                if is_tampered:
                    if "patch" in img_path and mod == "ela_noise":
                        if detected: stats[mod]["tp"] += 1
                        else: stats[mod]["fn"] += 1
                    elif "swap" in img_path and mod == "typography":
                        if detected: stats[mod]["tp"] += 1
                        else: stats[mod]["fn"] += 1
                    elif "clone" in img_path and mod == "copy_move":
                        if detected: stats[mod]["tp"] += 1
                        else: stats[mod]["fn"] += 1
                else:
                    if detected: stats[mod]["fp"] += 1
                    else: stats[mod]["tn"] += 1
                    
        docs_processed += 1

    print(f"\n================== RESULTADOS FORENSES (HF DATASET - BATCH {start_idx} to {start_idx + docs_processed - 1}) ==================")
    for mod, s in stats.items():
        total_tampered = s["tp"] + s["fn"]
        total_clean = s["fp"] + s["tn"]
        
        apcer = (s["fn"] / total_tampered * 100) if total_tampered > 0 else 0
        bpcer = (s["fp"] / total_clean * 100) if total_clean > 0 else 0
        
        print(f"[{mod}] APCER: {apcer:.1f}% | BPCER: {bpcer:.1f}% (Positivos Reales eval: {total_tampered}, Limpios eval: {total_clean})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch_size", type=int, default=5, help="Number of real invoices to process")
    parser.add_argument("--start_idx", type=int, default=0, help="Offset to start from in the HF dataset")
    args = parser.parse_args()
    
    evaluate_hf_batch(args.batch_size, args.start_idx)
