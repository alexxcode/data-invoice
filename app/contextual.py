import os
import json
from dotenv import load_dotenv

from google import genai
from google.genai import types
from tenacity import retry, wait_exponential, stop_after_attempt

from app.schema import FacturaEstructurada, AuditFinding, Provenance

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    # Fallback seguro para que no falle al importar si no hay API key aún en CI
    client = None
else:
    client = genai.Client(api_key=api_key)

@retry(wait=wait_exponential(multiplier=2, min=5, max=60), stop=stop_after_attempt(8))
def _call_gemini_pro_with_retry(prompt: str) -> str:
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2
        ),
    )
    return response.text

def flag_contextual_inconsistencies(factura: FacturaEstructurada) -> list[AuditFinding]:
    """
    Usa Gemini 2.5 Pro para evaluar lógicamente el contenido estructurado de la factura
    y buscar anomalías de negocio (tarifas incongruentes, impuestos atípicos, etc).
    """
    if not client:
        return []
        
    factura_json = factura.model_dump_json(indent=2)
    
    prompt = (
        "Eres un auditor financiero experto en facturación eléctrica en España.\n"
        "Analiza el siguiente JSON extraído de una factura.\n"
        "Busca anomalías lógicas de negocio (ejemplo: un importe exagerado para un concepto básico, "
        "nombres sospechosos que sugieran fraude, IVA que no corresponda al de energía eléctrica española que es típicamente 21% o reducido 5%, etc).\n\n"
        "NOTA: No hagas sumas aritméticas (ya las verificó un sistema previo). "
        "Concéntrate en la coherencia comercial e impositiva.\n\n"
        "Factura a evaluar:\n"
        f"{factura_json}\n\n"
        "Si encuentras inconsistencias contextuales, devuelve una lista JSON con este formato estricto:\n"
        "[\n"
        "  {\n"
        "    \"gravedad\": \"warning\",\n"
        "    \"tipo\": \"contexto\",\n"
        "    \"mensaje\": \"Explicación del hallazgo semántico\",\n"
        "    \"citas\": [ { \"page\": 1 } ]\n"
        "  }\n"
        "]\n"
        "Si todo es coherente, devuelve una lista vacía: []"
    )
    
    try:
        response_text = _call_gemini_pro_with_retry(prompt)
        
        data = json.loads(response_text)
        hallazgos = []
        for item in data:
            citas = [Provenance(**c) for c in item.get("citas", [])]
            hallazgos.append(AuditFinding(
                gravedad=item.get("gravedad", "info"),
                tipo=item.get("tipo", "contexto"),
                mensaje=item.get("mensaje", ""),
                citas=citas
            ))
        return hallazgos
    except Exception as e:
        print(f"Error evaluando contexto: {e}")
        return []
