import os
import fitz  # PyMuPDF
from PIL import Image
from dotenv import load_dotenv

from google import genai
from google.genai import types
from google.genai.errors import APIError
from tenacity import retry, wait_exponential, stop_after_attempt

# Importar el esquema que definimos en la Fase 2
from app.schema import FacturaEstructurada

load_dotenv()

# Inicializa el cliente explícitamente (evita problemas si .env está en blanco)
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY no encontrada.")
    
client = genai.Client(api_key=api_key)

@retry(wait=wait_exponential(multiplier=2, min=10, max=120), stop=stop_after_attempt(10))
def extract_invoice_data(pdf_path: str) -> FacturaEstructurada:
    """
    Toma un PDF, lo rasteriza página por página a imágenes y llama a Gemini Flash
    para extraer la información estructurada con validación Pydantic.
    """
    doc = fitz.open(pdf_path)
    images = []
    
    # Renderizar cada página a imagen (DPI 150 es buen equilibrio para OCR/VLM)
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=150)
        
        # Convertir el mapa de bits a imagen PIL para que la API de Google la procese
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
        
    doc.close()

    prompt = (
        "Eres Cotejo, un agente de auditoría experto en analizar facturas de energía eléctrica españolas. "
        "Analiza las siguientes imágenes que componen una factura. "
        "Extrae toda la información requerida en formato JSON estricto. "
        "MUY IMPORTANTE: Para cada campo principal, indica el número de página (empezando en 1) "
        "donde encontraste el dato, colocándolo en el campo 'provenance.page'.\n\n"
        "El JSON de salida debe seguir exactamente esta estructura:\n"
        f"{FacturaEstructurada.model_json_schema()}"
    )
    
    # Pasamos las imágenes y el prompt
    contents = images + [prompt]
    
    # Llamada a Gemini 2.5 Flash
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0  # Temperatura 0 para máxima precisión y determinismo
        ),
    )
    
    # Parseo manual del JSON devuelto
    return FacturaEstructurada.model_validate_json(response.text)

if __name__ == "__main__":
    # Prueba local ejecutando este archivo directamente
    sample_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples", "mock_factura_001.pdf")
    
    if os.path.exists(sample_path):
        print(f"Iniciando extracción multimodal de: {sample_path}")
        print("Llamando a Gemini 2.5 Flash...")
        factura_extraida = extract_invoice_data(sample_path)
        print("\n=== EXTRACCIÓN EXITOSA ===")
        print(factura_extraida.model_dump_json(indent=2))
    else:
        print(f"Error: No se encontró el archivo de muestra en {sample_path}")
