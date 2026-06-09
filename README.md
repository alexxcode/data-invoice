# Cotejo: Auditoría Documental y Scoring de Confianza (Identity Engineering)

Cotejo es un motor automatizado de auditoría y validación documental (KYC / Identity Engineering) diseñado para operar sobre facturas de servicios. Su objetivo principal no es solo extraer datos, sino ponderar la confianza de un documento para enrutarlo algorítmicamente (Auto-Approve, Human-in-the-loop, Auto-Reject).

## Arquitectura del Sistema

El sistema abandona el paradigma binario a favor de un pipeline compuesto por dos motores ortogonales:

### 1. Motor Visual (LLM) - Extracción y Confianza Base
Utiliza modelos multimodales (Gemini 2.5 Flash) para la rasterización de PDFs y extracción estructurada (Pydantic). 
El modelo extrae los datos y emite una heurística de **Extraction Confidence Score** (0.0 a 1.0) auto-reportada, basada en la calidad del escaneo, distorsión y ruido visual.

### 2. Motor Determinista - Reglas Duras (Zero-Hallucination)
Una capa algorítmica estricta que recalcula aritméticamente todos los importes, impuestos y subtotales, y verifica la existencia de campos legales obligatorios (CIF, CUPS).
- **Rol:** Es la única fuente capaz de emitir un rechazo automático y fulminante (`REJECT`).
- **Garantía:** El código no alucina. No genera Falsos Positivos matemáticos.

### 3. Motor Contextual (LLM) - Análisis Semántico
Utiliza un LLM secundario con temperatura baja para encontrar anomalías de negocio (ej. IVA del 50%, tarifas incongruentes).
- **Limitación Honesta:** El motor contextual es inherentemente ruidoso. Un hallazgo en esta capa **jamás desencadena un rechazo automático**. En su lugar, el diseño asume la posibilidad de una alucinación, penaliza el Score de Confianza global y deriva el documento a un operador humano.

## Políticas de Ruteo (KYC Flow)

El Orquestador Central (`agent.py`) consolida las señales ejecutando un **ruteo heurístico ponderado por confianza**:

1. **Auto-Approve (>0.90 Confianza):** Sin anomalías matemáticas, sin alertas contextuales, y con alta legibilidad visual. Procesamiento *Zero-Touch*.
2. **Manual Review / Human-in-the-Loop (0.60 - 0.90):** Documentos con alertas semánticas del LLM o con degradación visual severa (*layouts* atípicos como tickets miniatura).
3. **Auto-Reject (<0.60 o Fraude Matemático):** Fraude aritmético comprobado por reglas deterministas, omisión de identificadores fiscales, o documentos que no son facturas.

## Resultados de Evaluación Piloto (n=84)

El repositorio incluye un framework de evaluación rigurosa (`eval/eval_pipeline.py`) y un inyector de anomalías sintéticas (`data/inject_anomalies.py`) diseñado para someter al sistema a estrés geométrico y fraude sutil.

Resultados de la muestra ampliada (Baseline Esperado frente a Ground Truth inyectado):

| Métrica | Motor Determinista | Motor Contextual (LLM) |
|---|---|---|
| **Precisión (Precision)** | 1.00 (100%) | N/A (Solo emite Warnings) |
| **Recall (Tasa de Captura)** | 1.00 (100%) | (Pendiente de calibración profunda) |
| **Falsos Positivos** | 0 | 21 (Alucinaciones sobre ruido) |
| **Falsos Negativos** | 0* | 0 |

> ***Nota sobre los ceros absolutos:** Esta perfección estadística (0 FP/FN) es un artefacto exclusivo del tamaño de la muestra ampliada (n=84) y de su naturaleza sintética (PDFs generados digitalmente). En un entorno de producción real a gran escala (ej. dataset de 75k facturas escaneadas), la degradación visual, mala iluminación o arrugas causarán que el modelo de extracción visual cometa errores de lectura (ej. confundir un 8 con un 3). Estos errores de lectura (OCR/VLM) provocarán que el motor determinista falle las sumas, levantando alertas de "fraude aritmético" que en la realidad serán **Falsos Positivos** provocados por ruido visual. Esta tabla debe recalibrarse con el dataset masivo.*

**Conclusión Operativa:** La evaluación piloto demuestra empíricamente el valor del diseño de doble motor. El LLM es extraordinario para la lectura no estructurada pero sufre de una tasa de Falsos Positivos (ruido contextual) que hace inviable usarlo para tomar decisiones finales de rechazo. El Motor Determinista actúa como el ancla de la verdad, asegurando un sistema auditable y seguro para producción, asumiendo que los fallos de OCR derivarán facturas a revisión humana.

## Interfaz de Usuario y Ruteo (Demostración)

A continuación, capturas reales del sistema en funcionamiento, demostrando cómo la interfaz web clasifica visualmente los documentos tras ser procesados por la canalización determinista y el LLM:

<div align="center">
  <img src="imagenes_repo/Screenshot%202026-06-08%20225846.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20225900.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20232503.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20232704.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20234921.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20235349.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-09%20000218.png" width="45%" />
</div>

## Tecnologías Utilizadas

- **Core:** Python 3.12, FastAPI, Pydantic v2.
- **AI / VLM:** Google GenAI SDK (Gemini 2.5 Flash / Pro).
- **Procesamiento Documental:** PyMuPDF (Rasterización), ReportLab (Inyección sintética).

## Ejecución Local

```bash
# Instalación de dependencias
pip install -r requirements.txt

# Ejecutar Evaluación Empírica (Requiere API Key de pago)
python -m eval.eval_pipeline
```
