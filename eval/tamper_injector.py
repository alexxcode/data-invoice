import os
import random
import fitz
import pikepdf
from PIL import Image, ImageDraw
import numpy as np

def inject_metadata_tamper(input_pdf: str, output_pdf: str):
    pdf = pikepdf.Pdf.open(input_pdf)
    with pdf.open_metadata() as meta:
        meta['pdf:Producer'] = 'Adobe Photoshop CC'
    pdf.save(output_pdf, append=True) # incremental update
    return output_pdf, "metadata_tamper", None

def inject_resave_chain(input_img_path: str, output_img_path: str):
    img = Image.open(input_img_path).convert("RGB")
    # Save with low quality
    temp_path = output_img_path + ".temp.jpg"
    img.save(temp_path, "JPEG", quality=60)
    # Re-open and save with high quality
    img2 = Image.open(temp_path)
    img2.save(output_img_path, "JPEG", quality=95)
    os.remove(temp_path)
    return output_img_path, "resave_chain", None

def inject_region_patch(input_img_path: str, output_img_path: str, mask_path: str):
    img = Image.open(input_img_path).convert("RGB")
    w, h = img.size
    # Create mask
    mask = Image.new("1", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    img_draw = ImageDraw.Draw(img)
    # Create a random patch
    patch_w, patch_h = 200, 50
    x, y = random.randint(0, max(1, w - patch_w)), random.randint(0, max(1, h - patch_h))
    draw.rectangle([x, y, x + patch_w, y + patch_h], fill=1)
    # Paint white patch
    img_draw.rectangle([x, y, x + patch_w, y + patch_h], fill=(255, 255, 255))
    
    img.save(output_img_path)
    mask.save(mask_path)
    return output_img_path, "region_patch", mask_path

def generate_tampered_dataset(corpus_dir: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    samples = []
    if not os.path.exists(corpus_dir):
        print(f"Corpus directory {corpus_dir} does not exist.")
        return samples
        
    pdfs = [f for f in os.listdir(corpus_dir) if f.endswith(".pdf")]
    
    for i, pdf_name in enumerate(pdfs):
        input_pdf = os.path.join(corpus_dir, pdf_name)
        out_base = os.path.join(out_dir, f"tampered_{i}")
        
        # 1. Metadata tamper
        out_pdf = out_base + "_meta.pdf"
        samples.append(inject_metadata_tamper(input_pdf, out_pdf))
        
        # We need an image version for pixel manipulation
        try:
            doc = fitz.open(input_pdf)
            if len(doc) > 0:
                page = doc[0]
                pix = page.get_pixmap(dpi=150)
                img_path = out_base + ".png"
                pix.save(img_path)
                
                # 2. Region patch
                patch_out = out_base + "_patch.png"
                mask_out = out_base + "_patch_mask.png"
                samples.append(inject_region_patch(img_path, patch_out, mask_out))
                
                # 3. Resave chain
                resave_out = out_base + "_resave.jpg"
                samples.append(inject_resave_chain(img_path, resave_out))
        except Exception as e:
            print(f"Error processing {input_pdf}: {e}")

    return samples

if __name__ == "__main__":
    corpus = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples")
    out = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tampered_eval")
    generate_tampered_dataset(corpus, out)
    print("Tampered dataset generated.")
