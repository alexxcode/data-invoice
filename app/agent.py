import os
from typing import List

from app.schema import FacturaEstructurada, AuditFinding, AuditReport, PolicyDecision
from app.extraction import extract_invoice_data
from app.rules import run_deterministic_rules
from app.contextual import flag_contextual_inconsistencies

def process_batch(pdf_paths: List[str]) -> List[AuditReport]:
    """
    Orquesta el flujo principal:
    1. Extracción estructurada multimodal.
    2. Validación de reglas deterministas (por lote e individual).
    3. Validación contextual (LLM).
    4. Ensamblaje de Reportes.
    """
    
    # 1. Extracción Multimodal
    facturas_extraidas = []
    mapa_archivos = {}
    
    for path in pdf_paths:
        print(f"Extrayendo datos de {os.path.basename(path)}...")
        factura = extract_invoice_data(path)
        facturas_extraidas.append(factura)
        mapa_archivos[factura.numero_factura.value] = os.path.basename(path)
        
    # 2. Motor de Reglas Deterministas
    print("Ejecutando motor de reglas aritméticas y lógicas...")
    hallazgos_deterministas = run_deterministic_rules(facturas_extraidas)
    
    # 3. Motor Contextual y Generación de Reportes Finales
    reportes = []
    for factura in facturas_extraidas:
        numero = factura.numero_factura.value
        archivo = mapa_archivos[numero]
        print(f"Evaluando contexto profundo para {archivo}...")
        
        # Juntar hallazgos deterministas y contextuales
        hallazgos = hallazgos_deterministas.get(numero, [])
        hallazgos_contexto = flag_contextual_inconsistencies(factura)
        hallazgos.extend(hallazgos_contexto)
        
        # Determinar validez general de la factura
        es_valida = True
        has_critical_deterministic = False
        has_llm_warning = False
        
        for h in hallazgos:
            # EXCLUSIVO DETERMINISTA: Solo matemáticas o reglas duras pueden rechazar automáticamente.
            if h.tipo in ["aritmética", "faltante", "documento_invalido", "duplicado"]:
                es_valida = False
                has_critical_deterministic = True
            if h.tipo == "contexto":
                has_llm_warning = True
                
        # --- Lógica de Ruteo y Scoring KYC ---
        # Partimos de la confianza base que reporta la propia extracción visual
        final_confidence = factura.extraction_confidence
        policy = PolicyDecision.MANUAL_REVIEW
        
        if has_critical_deterministic:
            # Las matemáticas no mienten. Si hay fraude aritmético, rechazamos 100% seguros.
            policy = PolicyDecision.REJECT
            final_confidence = 1.0 
        elif has_llm_warning:
            # El LLM contextual detecta anomalías narrativas, pero asume ruido potencial.
            # Derivamos a humano y castigamos la confianza de extracción.
            policy = PolicyDecision.MANUAL_REVIEW
            final_confidence = final_confidence * 0.70
        else:
            # Factura inmaculada. Decidimos basándonos puramente en legibilidad.
            if final_confidence >= 0.90:
                policy = PolicyDecision.AUTO_APPROVE
            elif final_confidence >= 0.60:
                policy = PolicyDecision.MANUAL_REVIEW
            else:
                # Muy ilegible o de mala calidad
                policy = PolicyDecision.REJECT
                
        reportes.append(AuditReport(
            archivo_origen=archivo,
            hallazgos=hallazgos,
            es_valida=es_valida,
            policy_decision=policy,
            confidence_score=round(final_confidence, 4)
        ))
        
    return reportes

if __name__ == "__main__":
    # Prueba local
    samples_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples")
    archivos = [os.path.join(samples_dir, f) for f in os.listdir(samples_dir) if f.endswith(".pdf")]
    
    # Para probar rápido, procesamos solo 2
    if archivos:
        reportes = process_batch(archivos[:2])
        print("\n=== RESUMEN DE AUDITORÍA (Lote de Prueba) ===")
        for r in reportes:
            print(r.model_dump_json(indent=2))
