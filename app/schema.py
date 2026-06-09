from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

# --- Modelos de Procedencia (Provenance) ---
# Esto es crítico para la trazabilidad. Cada campo importante vendrá acompañado
# de la página donde Gemini Flash encontró el valor.

class Provenance(BaseModel):
    page: int = Field(description="Número de página donde se encontró el dato (ej. 1)")

class ExtractedString(BaseModel):
    value: str
    provenance: Provenance

class ExtractedFloat(BaseModel):
    value: float
    provenance: Provenance

# --- Modelos del Negocio (Factura) ---

class Cliente(BaseModel):
    nombre: ExtractedString = Field(description="Nombre completo del cliente o titular")
    cups: ExtractedString = Field(description="Código Unificado de Punto de Suministro (CUPS)")

class Emisor(BaseModel):
    nombre: ExtractedString = Field(description="Nombre de la compañía eléctrica")
    cif: ExtractedString = Field(description="CIF o identificador fiscal del emisor")

class Concepto(BaseModel):
    descripcion: str = Field(description="Descripción del cargo")
    importe: float = Field(description="Importe cobrado por este concepto")
    provenance: Provenance = Field(description="Página donde aparece este concepto")

class Totales(BaseModel):
    subtotal: ExtractedFloat = Field(description="Suma de conceptos antes de impuestos")
    impuestos: ExtractedFloat = Field(description="Total de impuestos aplicados (ej. IVA)")
    total_a_pagar: ExtractedFloat = Field(description="Total final a pagar de la factura")

class FacturaEstructurada(BaseModel):
    """
    Representación estructurada que Gemini Flash extraerá visualmente del PDF.
    """
    es_documento_auditable: bool = Field(description="True si el documento es realmente una factura, recibo o comprobante de cobro. False si es una carta, referencia bancaria, identidad, etc.")
    tipo_documento_detectado: str = Field(description="Clasificación de lo que el modelo está viendo (ej. 'Referencia Bancaria', 'Factura de Luz', 'Documento de Identidad', etc).")
    extraction_confidence: float = Field(description="Confianza del LLM en su propia extracción visual (de 0.0 a 1.0) basada en la legibilidad y claridad.")
    
    numero_factura: ExtractedString
    emisor: Emisor
    cliente: Cliente
    conceptos: List[Concepto]
    totales: Totales

# --- Modelos de Salida y Auditoría ---

class AuditFinding(BaseModel):
    gravedad: str = Field(description="Niveles: 'info', 'warning', 'critical'")
    tipo: str = Field(description="Ej: 'aritmética', 'duplicado', 'formato', 'contexto'")
    mensaje: str = Field(description="Explicación detallada de la anomalía")
    citas: List[Provenance] = Field(
        default_factory=list, 
        description="Páginas donde se encuentran los datos que generaron esta alerta"
    )

class PolicyDecision(str, Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECT = "REJECT"

class AuditReport(BaseModel):
    archivo_origen: str
    hallazgos: List[AuditFinding]
    es_valida: bool = Field(description="False si contiene errores críticos o aritméticos")
    policy_decision: PolicyDecision = Field(default=PolicyDecision.MANUAL_REVIEW, description="Decisión de ruteo del sistema")
    confidence_score: float = Field(default=0.0, description="Nivel de confianza ponderado de la auditoría (0.0 a 1.0)")
