import fitz
from PIL import Image

from app.forensics.classifier import classify_document
from app.forensics.models import DocumentClass


def test_native_digital_pdf():
    doc = fitz.open()
    page = doc.new_page()
    # > 200 caracteres de texto vectorial, sin imágenes
    text = "Linea de factura con descripcion del concepto cobrado. "
    for i in range(8):
        page.insert_text((72, 100 + i * 18), f"{i}: {text}", fontsize=10)
    assert classify_document(doc) == DocumentClass.NATIVE_DIGITAL


def test_image_document_is_scanned(tmp_path):
    # Un JPEG abierto directamente (caso del eval con imágenes de HF) debe
    # clasificar como SCANNED: cero texto, imagen cubriendo la página.
    img_path = str(tmp_path / "scan.jpg")
    Image.new("RGB", (800, 1000), color=(255, 255, 255)).save(img_path, "JPEG")
    doc = fitz.open(img_path)
    assert classify_document(doc) == DocumentClass.SCANNED
