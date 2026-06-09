import os
import json
import time
from typing import Dict, List

from app.agent import process_batch
from app.schema import PolicyDecision

def evaluate_system():
    eval_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples", "eval_dataset")
    gt_path = os.path.join(eval_dir, "ground_truth.json")
    
    with open(gt_path, "r") as f:
        ground_truth = json.load(f)
        
    archivos = [os.path.join(eval_dir, f) for f in ground_truth.keys() if f.endswith(".pdf")]
    
    print(f"Iniciando evaluación rigurosa sobre {len(archivos)} documentos...")
    start_time = time.time()
    
    # Procesar todo el lote
    reportes = process_batch(archivos)
    
    end_time = time.time()
    
    # --- MÉTRICAS ---
    # Determinista: Atrapar fraude matemático o campos faltantes obligatorios
    det_tp = 0 # Fraude atrapado por reglas
    det_fp = 0 # Falso positivo (reglas fallaron factura buena, no debería pasar jamás)
    det_fn = 0 # Fraude matemático que se escapó
    
    # Contextual: Falsos positivos del LLM
    llm_fp = 0 
    
    # Ruteo KYC
    auto_approved = 0
    manual_reviewed = 0
    rejected = 0
    
    for reporte in reportes:
        fname = os.path.basename(reporte.archivo_origen)
        gt = ground_truth[fname]
        
        # Estado real de la factura
        real_has_deterministic_error = gt["math_error"] or gt["missing_cups"] or gt["missing_cif"] or not gt["is_invoice"]
        
        # Hallazgos del agente
        agent_has_critical = any(h.gravedad == "critical" or h.tipo in ["aritmética", "faltante", "documento_invalido"] for h in reporte.hallazgos)
        agent_has_contextual = any(h.tipo == "contexto" for h in reporte.hallazgos)
        
        # Evaluación Determinista
        if real_has_deterministic_error and agent_has_critical:
            det_tp += 1
        elif real_has_deterministic_error and not agent_has_critical:
            det_fn += 1
            print(f"[!] FALSO NEGATIVO GRAVE: {fname} tenía fraude y pasó como limpia.")
        elif not real_has_deterministic_error and agent_has_critical:
            det_fp += 1
            print(f"[!] FALSO POSITIVO GRAVE: {fname} era limpia y las reglas la rechazaron.")
            
        # Evaluación Contextual (Solo medimos Falsos Positivos en este test de robustez)
        if not real_has_deterministic_error and agent_has_contextual:
            llm_fp += 1
            
        # Métricas de Ruteo
        if reporte.policy_decision == PolicyDecision.AUTO_APPROVE:
            auto_approved += 1
        elif reporte.policy_decision == PolicyDecision.MANUAL_REVIEW:
            manual_reviewed += 1
        else:
            rejected += 1

    # --- REPORTE ---
    total_anomalous = sum(1 for v in ground_truth.values() if v["math_error"] or v["missing_cups"] or v["missing_cif"] or not v["is_invoice"])
    
    # Precisión: De lo que el modelo dijo que era fraude, ¿cuántos lo eran realmente? (TP / (TP + FP))
    det_precision = det_tp / (det_tp + det_fp) if (det_tp + det_fp) > 0 else 1.0
    # Recall: Del total de fraudes reales, ¿cuántos atrapó el modelo? (TP / (TP + FN))
    det_recall = det_tp / (det_tp + det_fn) if (det_tp + det_fn) > 0 else 1.0
    
    print("\n" + "="*50)
    print("RESULTADOS DE EVALUACIÓN (RIGOR)")
    print("="*50)
    print(f"Tiempo total: {end_time - start_time:.2f}s")
    print(f"Promedio por doc: {(end_time - start_time) / len(archivos):.2f}s\n")
    
    print("--- MOTOR DETERMINISTA ---")
    print(f"Precisión: {det_precision:.2f}")
    print(f"Recall (Tasa de Atrapada): {det_recall:.2f}")
    print(f"Falsos Negativos (Fraude Escapado): {det_fn}")
    print(f"Falsos Positivos: {det_fp}\n")
    
    print("--- MOTOR CONTEXTUAL (LLM) ---")
    print(f"Falsos Positivos (Alucinaciones / Ruido): {llm_fp}")
    print("Conclusión: El LLM es inherentemente ruidoso y requiere estar acotado por Human-in-the-loop.\n")
    
    print("--- POLÍTICAS DE RUTEO (SIMULACIÓN KYC) ---")
    print(f"Auto-Approve (Sin fricción): {auto_approved}")
    print(f"Manual Review (Derivados a Humano): {manual_reviewed}")
    print(f"Auto-Reject (Rechazo Duro): {rejected}")
    print("="*50)

if __name__ == "__main__":
    evaluate_system()
