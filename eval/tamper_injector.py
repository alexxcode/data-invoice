import os
import random
import json
import fitz
import pikepdf
from PIL import Image, ImageDraw
import numpy as np

def inject_metadata_tamper(input_pdf: str, output_pdf: str):
    pdf = pikepdf.Pdf.open(input_pdf)
    with pdf.open_metadata() as meta:
        meta['pdf:Producer'] = 'Adobe Photoshop CC'
    pdf.save(output_pdf)
    return output_pdf, "metadata_tamper", None

def create_hard_negative(input_img_path: str, output_img_path: str):
    # Just re-save to simulate a scan without tampering
    img = Image.open(input_img_path).convert("RGB")
    img.save(output_img_path, "JPEG", quality=90)
    return output_img_path, "clean", None

def inject_resave_chain(input_img_path: str, output_img_path: str):
    img = Image.open(input_img_path).convert("RGB")
    temp_path = output_img_path + ".temp.jpg"
    img.save(temp_path, "JPEG", quality=60)
    img2 = Image.open(temp_path)
    img2.save(output_img_path, "JPEG", quality=95)
    os.remove(temp_path)
    return output_img_path, "resave_chain", None

def inject_region_patch(input_img_path: str, output_img_path: str, mask_path: str):
    # Base image is already a JPEG. We modify it and re-save as JPEG to trigger ELA
    img = Image.open(input_img_path).convert("RGB")
    w, h = img.size
    mask = Image.new("1", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    img_draw = ImageDraw.Draw(img)
    patch_w, patch_h = int(w*0.2), 50
    x, y = random.randint(0, max(1, w - patch_w)), random.randint(0, max(1, h - patch_h))
    draw.rectangle([x, y, x + patch_w, y + patch_h], fill=1)
    
    # Instead of a white box, copy a region and compress it terribly
    import io
    crop = img.crop((x, y, x + patch_w, y + patch_h))
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=10)
    buf.seek(0)
    bad_crop = Image.open(buf)
    
    img.paste(bad_crop, (x, y))
    img.save(output_img_path, "JPEG", quality=90)
    mask.save(mask_path)
    return output_img_path, "region_patch", mask_path

def inject_digit_swap(input_img_path: str, output_img_path: str, mask_path: str):
    img = Image.open(input_img_path).convert("RGB")
    w, h = img.size
    mask = Image.new("1", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    
    # Random block (simulating a digit)
    dw, dh = 15, 20
    src_x = random.randint(0, w - dw)
    src_y = random.randint(0, h - dh)
    crop = img.crop((src_x, src_y, src_x + dw, src_y + dh))
    
    dst_x = random.randint(0, w - dw)
    dst_y = random.randint(0, h - dh)
    
    img.paste(crop, (dst_x, dst_y))
    draw.rectangle([dst_x, dst_y, dst_x + dw, dst_y + dh], fill=1)
    
    img.save(output_img_path, "JPEG", quality=85)
    mask.save(mask_path)
    return output_img_path, "digit_swap", mask_path

def inject_clone_region(input_img_path: str, output_img_path: str, mask_path: str):
    img = Image.open(input_img_path).convert("RGB")
    w, h = img.size
    mask = Image.new("1", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    
    # Large block to ensure >6 AKAZE keypoints
    dw, dh = int(w * 0.4), 80
    
    # Select source from middle of page to avoid top 15% logo filter
    src_x = random.randint(10, w - dw - 10)
    src_y = random.randint(int(h * 0.2), h - dh - 10)
    crop = img.crop((src_x, src_y, src_x + dw, src_y + dh))
    
    dst_x = random.randint(10, w - dw - 10)
    dst_y = random.randint(int(h * 0.2), h - dh - 10)
    
    img.paste(crop, (dst_x, dst_y))
    draw.rectangle([dst_x, dst_y, dst_x + dw, dst_y + dh], fill=1)
    
    img.save(output_img_path, "JPEG", quality=85)
    mask.save(mask_path)
    return output_img_path, "copy_move", mask_path

def generate_tampered_dataset(corpus_dir: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    ground_truth = []
    
    pdfs = [f for f in os.listdir(corpus_dir) if f.endswith(".pdf")]
    
    for i, pdf_name in enumerate(pdfs):
        input_pdf = os.path.join(corpus_dir, pdf_name)
        out_base = os.path.join(out_dir, f"doc_{i}")
        
        # 1. Metadata tamper
        out_pdf = out_base + "_meta.pdf"
        p, t, m = inject_metadata_tamper(input_pdf, out_pdf)
        ground_truth.append({"image": p, "type": t, "mask": m, "class": "tampered"})
        
        # We need an image version for pixel manipulation
        try:
            doc = fitz.open(input_pdf)
            if len(doc) > 0:
                page = doc[0]
                # Convert directly to JPEG to establish compression baseline
                pix = page.get_pixmap(dpi=150)
                img_path = out_base + "_base.jpg"
                pil_img = Image.frombytes("RGB", [pix.w, pix.h], pix.samples)
                pil_img.save(img_path, "JPEG", quality=95)
                
                # 2. Region patch
                p, t, m = inject_region_patch(img_path, out_base + "_patch.jpg", out_base + "_patch_mask.png")
                ground_truth.append({"image": p, "type": t, "mask": m, "class": "tampered"})
                
                # 3. Resave chain
                p, t, m = inject_resave_chain(img_path, out_base + "_resave.jpg")
                ground_truth.append({"image": p, "type": t, "mask": m, "class": "tampered"})
                
                # 4. Digit swap
                p, t, m = inject_digit_swap(img_path, out_base + "_swap.jpg", out_base + "_swap_mask.png")
                ground_truth.append({"image": p, "type": t, "mask": m, "class": "tampered"})
                
                # 5. Copy Move
                p, t, m = inject_clone_region(img_path, out_base + "_clone.jpg", out_base + "_clone_mask.png")
                ground_truth.append({"image": p, "type": t, "mask": m, "class": "tampered"})
                
                # 5. Hard negative
                p, t, m = create_hard_negative(img_path, out_base + "_clean.jpg")
                ground_truth.append({"image": p, "type": t, "mask": m, "class": "clean"})
                
        except Exception as e:
            print(f"Error processing {input_pdf}: {e}")

    with open(os.path.join(out_dir, "ground_truth.json"), "w") as f:
        json.dump(ground_truth, f, indent=2)
    return ground_truth

if __name__ == "__main__":
    corpus = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples")
    out = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tampered_eval")
    generate_tampered_dataset(corpus, out)
    print("Tampered dataset generated with ground truth.")
