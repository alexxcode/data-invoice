# Cotejo: Motor Ortogonal de Auditoría Documental y Ruteo Heurístico (Identity Engineering)

Cotejo es un sistema avanzado de **Identity Engineering y KYC (Know Your Customer) B2B**, diseñado para la extracción estructurada, auditoría matemática y evaluación semántica de facturas de servicios. 

A diferencia de los enfoques tradicionales que confían ciegamente en el Reconocimiento Óptico de Caracteres (OCR) o en Modelos de Lenguaje Grande (LLMs) propensos a alucinaciones, Cotejo propone una **arquitectura de doble motor ortogonal**: acopla la asombrosa capacidad de lectura no estructurada de un Modelo de Visión-Lenguaje (VLM) con un motor determinista de validación aritmética inflexible.

---

## 1. Arquitectura del Sistema (Pipeline de Evaluación)

El flujo de procesamiento abandona el paradigma binario convencional (Válido/Inválido) y adopta una canalización en tres fases que pondera la **confiabilidad del dato extraído**:

### Fase 1: Extracción Multimodal y Heurística de Confianza Base
El sistema prescinde de motores OCR frágiles basados en coordenadas. Utiliza rasterización de alta fidelidad (vía `PyMuPDF` a 150 DPI) para convertir documentos PDF complejos en tensores visuales que son procesados por **Gemini 2.5 Flash**. 
*   **Temperatura 0.0:** Se fuerza al modelo fundacional a un estado casi-determinista para minimizar la estocasticidad en la extracción JSON (vía Pydantic).
*   **Extraction Confidence Score:** El VLM emite una heurística probabilística auto-reportada (0.0 a 1.0) sobre la legibilidad del documento, penalizando ruido, desenfoque geométrico o degradación del escaneo.

### Fase 2: Motor Determinista (El Ancla de la Verdad)
Para contrarrestar la inherente falta de rigor matemático de los modelos transformadores, los datos extraídos pasan por un pipeline algorítmico estricto escrito en Python puro (`app/rules.py`).
*   **Lógica Fundamental:** Verifica la universalidad contable: `Subtotal + Impuestos = Total Declarado` (tolerando sesgos de redondeo flotante de hasta ±0.05).
*   **Campos Críticos:** Valida la presencia de invariantes legales como identificadores fiscales (CIF) y códigos de punto de suministro (CUPS).
*   **Mitigación de Riesgo Estructural:** Este motor es **la única entidad autorizada** en el sistema para emitir un fallo de Rechazo Automático (`REJECT`). Garantiza *Zero-Hallucination* en la evaluación de fraude matemático.

### Fase 3: Análisis Semántico Contextual
Se ejecuta un segundo LLM en paralelo para auditar anomalías de lógica de negocio o fraude blando (ej. tarifas energéticas incongruentes con el mercado, discrepancias de IVA injustificadas).
*   **Limitación Deliberada de Autoridad:** Asumiendo empíricamente que los LLMs generan ruido (Falsos Positivos) en tareas de razonamiento contextual, **ningún hallazgo en esta capa puede desencadenar un rechazo duro**. La penalización se restringe a degradar el documento hacia una revisión humana obligatoria.

---

## 2. Políticas de Ruteo y Toma de Decisiones (KYC Flow)

El Orquestador Central (`app/agent.py`) consolida las señales de los tres ejes anteriores para emitir una `PolicyDecision` final, optimizando el rendimiento operativo (STP - *Straight Through Processing*):

| Nivel de Ruteo | Lógica Computacional | Aplicación Práctica |
|---|---|---|
| **🟢 AUTO_APPROVE** | `Confidence > 0.90` ∧ `Det_Errors == 0` ∧ `Ctx_Warnings == 0` | Facturas perfectas, sin anomalías contables ni semánticas. Procesamiento *Zero-Touch*. |
| **🟡 MANUAL_REVIEW** | `0.60 ≤ Confidence ≤ 0.90` ∨ `Ctx_Warnings > 0` | El documento presenta ambigüedades semánticas detectadas por el LLM o su degradación visual (ej. fotos borrosas) reduce la confianza estadística de la extracción. Requiere intervención humana (*Human-in-the-loop*). |
| **🔴 REJECT** | `Confidence < 0.60` ∨ `Det_Errors > 0` | Fraude matemático algorítmicamente comprobado, omisión de identificadores legales, o documento ilegible/falsificado. |

---

## 3. Metodología de Evaluación Empírica

El proyecto integra un arnés de pruebas de caja blanca (`eval/eval_pipeline.py`) y un inyector de entropía sintética (`data/inject_anomalies.py`) que somete el motor a distorsiones geométricas (rotación de *bounding boxes*, layouts tipo ticket) y anomalías contables calculadas.

### Resultados de Evaluación Piloto (n=84)

Resultados de la muestra ampliada (Baseline Esperado frente a *Ground Truth* inyectado):

| Métrica | Motor Determinista (Matemático) | Motor Contextual (Semántico) |
|---|---|---|
| **Precisión (Precision)** | 1.00 (100%) | N/A (Restringido a emitir *Warnings*) |
| **Recall (Tasa de Captura)** | 1.00 (100%) | *Pendiente de calibración estadística profunda* |
| **Falsos Positivos (FP)** | 0 | 21 (Ruido y alucinaciones contextuales) |
| **Falsos Negativos (FN)** | 0* | 0 |

> ***Nota sobre Limitaciones del Baseline:** La perfección estadística del motor determinista (0 FP/FN) refleja exclusivamente el rendimiento sobre documentos de generación digital nativa (sintéticos). En un ecosistema de producción a gran escala (ej. dataset masivo de 75,000 facturas digitalizadas), la varianza óptica y el ruido de captura causarán invariablemente errores de inferencia en el motor VLM (ej. confundir un dígito '8' con un '3'). Estas disrupciones en la extracción provocarán fallos asimétricos en la validación aritmética, manifestándose empíricamente como **Falsos Positivos Deterministas**. La arquitectura asume esta degradación ruteando dichos artefactos eficientemente hacia `MANUAL_REVIEW`.*

**Conclusión Arquitectónica:** Los datos demuestran el riesgo sistémico de otorgar autoridad de rechazo final a Modelos Fundacionales debido a su alta entropía (21 FPs). El aislamiento de responsabilidades entre el VLM (solo extracción) y el Algoritmo (validación de verdad) constituye el pilar de un sistema seguro y auditable para la capa institucional.

---

## 4. Interfaz de Usuario (Demostración Visual)

El sistema provee una capa de renderizado cliente-servidor que expone la trazabilidad de origen (*data provenance*), subrayando explícitamente en qué página del PDF se fundamentó el modelo para cada extracción y mostrando visualmente la política de ruteo aplicada:

<div align="center">
  <img src="imagenes_repo/Screenshot%202026-06-08%20225846.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20225900.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20232503.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20232704.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20234921.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20235349.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-09%20000218.png" width="45%" />
</div>

---

## 5. Pila Tecnológica y Dependencias

- **Backend / API Core:** Python 3.12, FastAPI (Concurrencia asíncrona), Uvicorn.
- **Validación de Datos:** Pydantic v2 (Validación de esquema estricto y tipado de Modelos de IA).
- **Inteligencia Artificial:** Google GenAI SDK (Gemini 2.5 Flash / Pro Multimodal).
- **Tratamiento Documental:** PyMuPDF (Rasterización de Tensores Vectoriales), ReportLab (Generación y mutación de PDF sintéticos).
- **Resiliencia Operativa:** Tenacity (Implementación de *Exponential Backoff* para *Rate Limits* de API).
- **Despliegue (Nube):** Docker, Google Cloud Run (Serverless), Google Cloud Build.

---

## 6. Despliegue y Ejecución en Entorno Local

**Clonación y Preparación de Entorno:**
```bash
git clone https://github.com/alexxcode/data-invoice.git
cd data-invoice
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Configuración de Variables de Entorno (`.env`):**
```env
GEMINI_API_KEY="tu_api_key_de_google_ai_studio"
```

**Ejecución del Servidor ASGI:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```
*La API estará disponible en `http://localhost:8080/docs` y la interfaz web en `http://localhost:8080/ui/index.html`.*

**Ejecución del Arnés de Evaluación Empírica:**
*(Requiere aprovisionamiento de cuota de API corporativa debido a los límites estandarizados por minuto).*
```bash
python -m eval.eval_pipeline
```
