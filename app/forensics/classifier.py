import fitz
from .models import DocumentClass

def max_image_coverage(doc: fitz.Document) -> float:
    max_ratio = 0.0
    for page in doc:
        page_area = page.rect.width * page.rect.height
        image_area = 0.0
        # get_image_info returns a list of dicts with 'bbox'
        images = page.get_image_info()
        for img in images:
            rect = img['bbox']
            # bbox is a tuple (x0, y0, x1, y1)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            image_area += w * h
        ratio = image_area / page_area if page_area > 0 else 0
        if ratio > max_ratio:
            max_ratio = ratio
    return max_ratio

def classify_document(doc: fitz.Document) -> DocumentClass:
    text_chars = sum(len(p.get_text()) for p in doc)
    image_area_ratio = max_image_coverage(doc)
    
    if text_chars > 200 and image_area_ratio < 0.5:
        return DocumentClass.NATIVE_DIGITAL
    if text_chars < 50 and image_area_ratio > 0.9:
        return DocumentClass.SCANNED
    return DocumentClass.HYBRID
