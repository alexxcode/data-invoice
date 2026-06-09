from typing import List, Dict
from app.schema import FacturaEstructurada, AuditFinding, Provenance

def check_arithmetic(factura: FacturaEstructurada) -> List[AuditFinding]:
    findings = []
    
    # 1. Validar que Subtotal + Impuestos = Total (con tolerancia de redondeo de 0.05)
    subtotal = factura.totales.subtotal.value
    impuestos = factura.totales.impuestos.value
    total_calculado = subtotal + impuestos
    total_declarado = factura.totales.total_a_pagar.value
    
    if abs(total_calculado - total_declarado) > 0.05:
        citas = [
            factura.totales.subtotal.provenance,
            factura.totales.impuestos.provenance,
            factura.totales.total_a_pagar.provenance
        ]
        findings.append(AuditFinding(
            gravedad="critical",
            tipo="aritmética",
            mensaje=f"Error matemático: El subtotal ({subtotal}) + impuestos ({impuestos}) es {total_calculado}, pero el total a pagar indica {total_declarado}.",
            citas=citas
        ))
        
    # 2. (REMOVIDO) Validar que la suma de conceptos = Subtotal
    # Se elimina esta regla por ser excesivamente frágil: el LLM a menudo extrae
    # los impuestos o cargos extra como "conceptos" adicionales, lo que hace que 
    # la suma sobrepase el subtotal matemático, causando Falsos Positivos de fraude.
    return findings

def check_missing_fields(factura: FacturaEstructurada) -> List[AuditFinding]:
    findings = []
    
    if not factura.emisor.cif.value.strip():
        findings.append(AuditFinding(
            gravedad="warning",
            tipo="faltante",
            mensaje="El CIF del emisor está vacío o no se pudo extraer.",
            citas=[factura.emisor.cif.provenance]
        ))
        
    if not factura.cliente.cups.value.strip() or len(factura.cliente.cups.value) < 10:
        findings.append(AuditFinding(
            gravedad="warning",
            tipo="faltante",
            mensaje=f"El código CUPS parece inválido o ausente ({factura.cliente.cups.value}).",
            citas=[factura.cliente.cups.provenance]
        ))
        
    return findings

def check_duplicates_in_batch(facturas: List[FacturaEstructurada]) -> Dict[str, List[AuditFinding]]:
    # Devuelve un diccionario donde la key es el numero de factura, value es lista de findings
    resultados = {f.numero_factura.value: [] for f in facturas}
    
    # Agrupar por identificadores críticos (emisor_cif + numero_factura + total)
    vistos = {}
    
    for fac in facturas:
        llave = f"{fac.emisor.cif.value}_{fac.numero_factura.value}_{fac.totales.total_a_pagar.value}"
        if llave in vistos:
            # Es un duplicado
            citas_original = vistos[llave]
            citas_actual = [fac.numero_factura.provenance, fac.totales.total_a_pagar.provenance]
            
            resultados[fac.numero_factura.value].append(AuditFinding(
                gravedad="critical",
                tipo="duplicado",
                mensaje=f"Esta factura parece ser un duplicado de otra en el mismo lote (Mismo emisor, número y monto).",
                citas=citas_actual
            ))
        else:
            vistos[llave] = [fac.numero_factura.provenance]
            
    return resultados

def run_deterministic_rules(facturas: List[FacturaEstructurada]) -> Dict[str, List[AuditFinding]]:
    """
    Ejecuta todas las reglas deterministas sobre un lote de facturas.
    Devuelve un diccionario {numero_factura: [hallazgos...]}
    """
    hallazgos_por_factura = {f.numero_factura.value: [] for f in facturas}
    
    # Revisión de duplicados a nivel lote
    duplicados = check_duplicates_in_batch(facturas)
    
    # Revisión individual
    for f in facturas:
        h = []
        
        # 0. Verificación de Clasificación de Documento
        if not f.es_documento_auditable:
            h.append(AuditFinding(
                gravedad="critical",
                tipo="documento_invalido",
                mensaje=f"Documento rechazado: El sistema ha detectado que esto es un(a) '{f.tipo_documento_detectado}', no una factura auditable. Se detiene la auditoría de este archivo.",
                citas=[]
            ))
            hallazgos_por_factura[f.numero_factura.value] = h
            continue # Si no es factura, saltamos las reglas matemáticas
            
        h.extend(check_arithmetic(f))
        h.extend(check_missing_fields(f))
        
        # Sumar los hallazgos de duplicados
        h.extend(duplicados.get(f.numero_factura.value, []))
        
        hallazgos_por_factura[f.numero_factura.value] = h
        
    return hallazgos_por_factura
