import os
from concurrent.futures import ThreadPoolExecutor
from typing import List

from app.schema import FacturaEstructurada, AuditFinding, AuditReport, PolicyDecision
from app.rules import run_deterministic_rules
from app.contextual import flag_contextual_inconsistencies
from app.forensics.models import ForensicReport

# Celery solo si hay broker configurado (Dockerfile lo exporta en Cloud Run).
# En local sin Redis el lote se procesa en modo síncrono con threads.
USE_CELERY = bool(os.environ.get("CELERY_BROKER_URL"))


def _run_jobs(pdf_paths: List[str]) -> List[dict]:
    """Extracción (LLM) + forense por documento, en paralelo.

    Devuelve una lista (mismo orden que pdf_paths) de dicts:
    {"path": str, "factura": FacturaEstructurada | None, "forense": ForensicReport | None}
    """
    results = []

    if USE_CELERY:
        from app.tasks import extract_task, forensics_task
        jobs = []
        for path in pdf_paths:
            print(f"Despachando tareas (Extracción + Forense) para {os.path.basename(path)}...")
            jobs.append((path, extract_task.delay(path), forensics_task.delay(path)))

        print("Esperando resultados concurrentes...")
        for path, extract_job, forensic_job in jobs:
            entry = {"path": path, "factura": None, "forense": None}
            try:
                entry["factura"] = FacturaEstructurada(**extract_job.get(timeout=300))
            except Exception as e:
                print(f"Error en extracción para {path}: {e}")
            try:
                entry["forense"] = ForensicReport(**forensic_job.get(timeout=300))
            except Exception as e:
                print(f"Error en forense para {path}: {e}")
            results.append(entry)
        return results

    # Modo síncrono local: extracción es I/O-bound (API) y forense CPU-bound;
    # threads bastan para solaparlos sin requerir Redis/Celery.
    from app.extraction import extract_invoice_data
    from app.forensics.scorer import run_forensics

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = []
        for path in pdf_paths:
            print(f"Procesando localmente (Extracción + Forense) {os.path.basename(path)}...")
            futures.append((path, pool.submit(extract_invoice_data, path), pool.submit(run_forensics, path)))

        for path, extract_fut, forensic_fut in futures:
            entry = {"path": path, "factura": None, "forense": None}
            try:
                entry["factura"] = extract_fut.result()
            except Exception as e:
                print(f"Error en extracción para {path}: {e}")
            try:
                entry["forense"] = forensic_fut.result()
            except Exception as e:
                print(f"Error en forense para {path}: {e}")
            results.append(entry)
    return results


def process_batch(pdf_paths: List[str]) -> List[AuditReport]:
    """
    Orquesta el flujo principal:
    1. Extracción estructurada multimodal + forense concurrente (Celery o local).
    2. Validación de reglas deterministas (por lote e individual).
    3. Validación contextual (LLM).
    4. Ensamblaje de Reportes.

    Todo el estado se indexa por ARCHIVO, no por numero_factura: dos archivos
    con el mismo número (caso duplicado, central en este dominio) no deben
    pisarse entre sí.
    """
    entries = [e for e in _run_jobs(pdf_paths) if e["factura"] is not None]

    facturas_extraidas = [e["factura"] for e in entries]

    # Motor de Reglas Deterministas (devuelve hallazgos por numero_factura;
    # dos archivos con el mismo numero comparten esos hallazgos, que incluyen
    # el finding de duplicado)
    print("Ejecutando motor de reglas aritméticas y lógicas...")
    hallazgos_deterministas = run_deterministic_rules(facturas_extraidas)

    reportes = []
    for entry in entries:
        factura = entry["factura"]
        forense = entry["forense"]
        archivo = os.path.basename(entry["path"])
        numero = factura.numero_factura.value
        print(f"Evaluando contexto profundo y ensamblando reporte para {archivo}...")

        # Juntar hallazgos
        hallazgos = list(hallazgos_deterministas.get(numero, []))
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
