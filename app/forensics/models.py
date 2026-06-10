from pydantic import BaseModel
from enum import Enum
from typing import List, Optional, Tuple

class DocumentClass(str, Enum):
    NATIVE_DIGITAL = "native_digital"   # texto vectorial, generado por software
    SCANNED = "scanned"                 # página = una imagen grande
    HYBRID = "hybrid"                   # mezcla (típico de PDFs editados)

class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class ForensicFinding(BaseModel):
    technique: str                # "ela" | "copy_move" | "noise" | "typography" | "metadata"
    severity: Severity
    page: int
    bbox: Optional[Tuple[float, float, float, float]] = None
    score: float                  # 0..1, intra-técnica
    explanation: str              # texto para el revisor humano
    overlay_path: Optional[str] = None      # PNG de evidencia

class ForensicReport(BaseModel):
    document_class: DocumentClass
    findings: List[ForensicFinding] = []
    forensic_risk: float = 0.0          # 0..1 agregado
    requires_review: bool = False
