import os
from typing import List

from app.schema import FacturaEstructurada, AuditFinding, AuditReport, PolicyDecision
from app.rules import run_deterministic_rules
from app.contextual import flag_contextual_inconsistencies
from app.forensics.models import ForensicReport
from app.tasks import extract_task, forensics_task

def process_batch(pdf_paths: List[str]) -> List[AuditReport]:
    """
    Orquesta el flujo principal:
    1. Extracción estructurada multimodal (Celery).
    2. Evaluación forense concurrente (Celery).
    3. Validación de reglas deterministas (por lote e individual).
    4. Validación contextual (LLM).
    5. Ensamblaje de Reportes.
    """
    
    # 1 y 2. Despachar a Celery
    async_results = []
    for path in pdf_paths:
        print(f"Despachando tareas (Extracción + Forense) para {os.path.basename(path)}...")
        extract_job = extract_task.delay(path)
        forensic_job = forensics_task.delay(path)
        async_results.append({
            "path": path,
            "extract_job": extract_job,
            "forensic_job": forensic_job
        })
        
    facturas_extraidas = []
    mapa_archivos = {}
    forensic_reports = {}
    
    print("Esperando resultados concurrentes...")
    for res in async_results:
        path = res["path"]
        numero = ""
        try:
            factura_dict = res["extract_job"].get(timeout=300)
            factura = FacturaEstructurada(**factura_dict)
            facturas_extraidas.append(factura)
            numero = factura.numero_factura.value
            mapa_archivos[numero] = os.path.basename(path)
        except Exception as e:
            print(f"Error en extracción para {path}: {e}")
            continue
            
        try:
            report_dict = res["forensic_job"].get(timeout=300)
            forensic_reports[numero] = ForensicReport(**report_dict)
        except Exception as e:
            print(f"Error en forense para {path}: {e}")
            forensic_reports[numero] = None

    # 3. Motor de Reglas Deterministas
    print("Ejecutando motor de reglas aritméticas y lógicas...")
    hallazgos_deterministas = run_deterministic_rules(facturas_extraidas)
    
    # 4 y 5. Motor Contextual y Generación de Reportes Finales
    reportes = []
    for factura in facturas_extraidas:
        numero = factura.numero_factura.value
        archivo = mapa_archivos[numero]
        forense = forensic_reports.get(numero)
        print(f"Evaluando contexto profundo y ensamblando reporte para {archivo}...")
        
        # Juntar hallazgos
        hallazgos = hallazgos_deterministas.get(numero, [])
        hallazgos_contexto = flag_contextual_inconsistencies(factura)
        hallazgos.extend(hallazgos_contexto)
        
        es_valida = True
        has_critical_deterministic = False
        has_llm_warning = False
        
        for h in hallazgos:
            # EXCLUSIVO DETERMINISTA
            if h.tipo in ["aritmética", "faltante", "documento_invalido", "duplicado"]:
                es_valida = False
                has_critical_deterministic = True
            if h.tipo == "contexto":
                has_llm_warning = True
                
        # --- Lógica de Ruteo y Scoring KYC ---
        final_confidence = factura.extraction_confidence
        policy = PolicyDecision.MANUAL_REVIEW
        
        requires_forensic_review = forense.requires_review if forense else False
        
        if has_critical_deterministic:
            # Las matemáticas no mienten
            policy = PolicyDecision.REJECT
            final_confidence = 1.0 
        elif has_llm_warning or requires_forensic_review:
            # Derivamos a humano y castigamos la confianza
            policy = PolicyDecision.MANUAL_REVIEW
            if has_llm_warning:
                final_confidence = final_confidence * 0.70
            if requires_forensic_review:
                final_confidence = final_confidence * 0.80
        else:
            # Factura inmaculada
            if final_confidence >= 0.90:
                # Modificado a AUTO_APPROVE solo si el risk forense es bajo, el forense lo determina en su requires_review = False
                policy = PolicyDecision.AUTO_APPROVE
            elif final_confidence >= 0.60:
                policy = PolicyDecision.MANUAL_REVIEW
            else:
                policy = PolicyDecision.REJECT
                
        reportes.append(AuditReport(
            archivo_origen=archivo,
            hallazgos=hallazgos,
            es_valida=es_valida,
            policy_decision=policy,
            confidence_score=round(final_confidence, 4),
            forensic_report=forense
        ))
        
    return reportes

if __name__ == "__main__":
    # Prueba local
    samples_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples")
    archivos = [os.path.join(samples_dir, f) for f in os.listdir(samples_dir) if f.endswith(".pdf")]
    
    if archivos:
        reportes = process_batch(archivos[:2])
        print("\n=== RESUMEN DE AUDITORÍA (Lote de Prueba) ===")
        for r in reportes:
            print(r.model_dump_json(indent=2))
