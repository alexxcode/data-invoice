# Cotejo: Auditoría Documental y Scoring de Confianza (Identity Engineering)

Cotejo es un motor automatizado de auditoría y validación documental (KYC / Identity Engineering) diseñado para operar sobre facturas de servicios. Su objetivo principal no es solo extraer datos, sino **calibrar estadísticamente la confianza** de un documento para enrutarlo automáticamente (Auto-Approve, Human-in-the-loop, Auto-Reject).

## Arquitectura del Sistema

El sistema abandona el paradigma binario (Válido/Inválido) a favor de un pipeline de evaluación bayesiana compuesto por dos motores ortogonales:

### 1. Motor Visual (LLM) - Extracción y Confianza Base
Utiliza modelos multimodales (Gemini 2.5 Flash) para la rasterización de PDFs y extracción estructurada (Pydantic). 
El modelo no solo extrae los datos, sino que emite un **Extraction Confidence Score** (0.0 a 1.0) basado en la calidad del escaneo, distorsión geométrica (rotaciones) y ruido visual.

### 2. Motor Determinista - Reglas Duras (Zero-Hallucination)
Una capa algorítmica estricta que recalcula aritméticamente todos los importes, impuestos y subtotales. Además, verifica la existencia de campos legales obligatorios (CIF, CUPS).
- **Rol:** Es la única fuente capaz de emitir un rechazo automático y fulminante (`REJECT`).
- **Precision:** 1.0 (No genera Falsos Positivos matemáticos).

### 3. Motor Contextual (LLM) - Análisis Semántico
Utiliza un LLM secundario con temperatura baja para encontrar anomalías de negocio (tarifas incongruentes, impuestos atípicos).
- **Limitación Honesta:** El motor contextual es inherentemente ruidoso. Dado que los LLM son propensos a alucinaciones semánticas, cualquier hallazgo en esta capa **jamás** desencadena un rechazo automático. En su lugar, penaliza el Score de Confianza global y deriva el documento a un operador humano.

## Políticas de Ruteo (KYC Flow)

El Orquestador Central (`agent.py`) consolida las señales de los motores y ejecuta el ruteo:

1. **Auto-Approve (>0.90 Confianza):** Sin anomalías matemáticas, sin alertas contextuales, y con alta legibilidad visual. Procesamiento *Zero-Touch*.
2. **Manual Review / Human-in-the-Loop (0.60 - 0.90):** Documentos con alertas semánticas del LLM o con degradación visual severa (baja resolución, *layouts* atípicos como tickets).
3. **Auto-Reject (<0.60 o Fraude Matemático):** Fraude aritmético comprobado, omisión de identificadores fiscales, o documentos que no son facturas (ej. cartas o referencias bancarias).

## Evaluación y Robustez (Pipeline)

El repositorio incluye un framework de evaluación rigurosa (`eval/eval_pipeline.py`) y un inyector de anomalías sintéticas (`data/inject_anomalies.py`).

El inyector genera un *Ground Truth Dataset* local con la llamada "Cola Larga" de degradación:
- Facturas estándar limpias.
- Facturas en formato *Ticket de caja* (stress testing geométrico).
- Documentos rotados 90 grados.
- Fraudes aritméticos sutiles inyectados.

El pipeline evalúa el rendimiento calculando la **Precisión y Recall de forma independiente** para el motor de reglas y el LLM, evidenciando empíricamente la necesidad del *Human-in-the-loop* para mitigar la tasa de falsos positivos generados por el análisis contextual de la Inteligencia Artificial.

## Tecnologías Utilizadas

- **Core:** Python 3.12, FastAPI, Pydantic v2.
- **AI / VLM:** Google GenAI SDK (Gemini 2.5 Flash / Pro).
- **Procesamiento Documental:** PyMuPDF (Rasterización), ReportLab (Inyección sintética).
- **Infraestructura:** Docker, Google Cloud Run, Cloud Build (Serverless).

## Ejecución Local

```bash
# Instalación de dependencias
pip install -r requirements.txt

# Iniciar API Local
python -m uvicorn app.main:app --reload

# Ejecutar Evaluación Empírica (Requiere API Key de pago)
python -m eval.eval_pipeline
```
