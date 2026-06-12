# Cotejo: Motor Dual de Auditoría Documental y Ruteo Heurístico

Cotejo es un sistema de extracción y validación de facturas diseñado bajo una premisa central: **los Modelos de Lenguaje (LLMs) alucinan**. 

En lugar de confiar el proceso completo a una IA generativa, el sistema aísla el proceso de lectura (delegado al LLM) del proceso de validación final (delegado a un código determinista tradicional). Esto permite rutar los documentos de forma segura sin depender de que un LLM tome la decisión de rechazo.

> **Documentos clave:** [THREAT_MODEL.md](THREAT_MODEL.md) define contra qué adversario y bajo
> qué canal de transmisión se mide la detección (sin esto las métricas no son interpretables).
> [powerUp.md](powerUp.md) es el plan de investigación y el registro de resultados por fase.
> El pipeline experimental completo se reproduce con `python reproduce.py --skip-vlm`.

---

## 1. Arquitectura del Sistema

El pipeline de procesamiento se divide en tres capas con responsabilidades estrictamente separadas:

### Fase 1: Extracción Visual (VLM)
Convierte documentos PDF en mapas de bits (imágenes a 150 DPI) usando `PyMuPDF`. Estas imágenes se envían a Gemini 2.5 Flash operando a Temperatura 0.0 para forzar la máxima predictibilidad en la estructura JSON devuelta.
*   **Confidence Score:** El modelo de lenguaje emite un valor numérico estimado libremente por él mismo (0.0 a 1.0) sobre la legibilidad visual del documento. No es un valor estadísticamente calibrado.

### Fase 2: Motor Determinista (Matemático)
Script en Python puro (`app/rules.py`) que audita los datos que el LLM extrajo en la Fase 1.
*   **Regla principal:** Verifica que `Subtotal + Impuestos = Total Declarado`.
*   **Identificadores:** Revisa si existen las cadenas de texto del CIF y el CUPS.
*   **Autoridad:** Es el **único** componente del sistema autorizado para emitir un fallo de Rechazo (`REJECT`). Como el código no alucina, garantiza que no habrá Falsos Positivos causados por un error lógico de la máquina.

### Fase 3: Análisis Semántico Contextual
Se ejecuta un segundo prompt al LLM buscando inconsistencias en la lógica de negocio (ej. IVA del 50%, tarifas incongruentes).
*   **Limitación de Autoridad:** Como las inferencias del LLM en texto son ruidosas y propensas a Falsos Positivos, cualquier hallazgo en esta capa solo emite una advertencia (`Warning`). **Jamás** causa un rechazo automático; solo fuerza una revisión manual.

---

## 2. Políticas de Ruteo

El Orquestador (`app/agent.py`) decide a dónde enviar la factura usando umbrales fijos sobre el Score de Confianza del LLM y las reglas deterministas:

*   **🟢 AUTO_APPROVE:** `Score > 0.90` y cero errores matemáticos. La factura se procesa sin intervención humana.
*   **🟡 MANUAL_REVIEW:** `0.60 ≤ Score ≤ 0.90` o si el LLM detectó anomalías semánticas. Un operador humano debe revisar el documento.
*   **🔴 REJECT:** `Score < 0.60` o fraude matemático (`Subtotal + Impuestos != Total`).

---

## 3. Metodología de Evaluación y Limitaciones (n=84)

Resultados de la muestra ampliada ejecutada contra un inyector de anomalías sintéticas (*Baseline* vs *Ground Truth*):

| Métrica | Motor Determinista (Python) | Motor Contextual (LLM) |
|---|---|---|
| **Precisión (Precision)** | 1.00 (100%) | N/A (Solo emite Warnings) |
| **Recall (Tasa de Captura)** | 1.00 (100%) | No calibrado |
| **Falsos Positivos (FP)** | 0 | 21 (Ruido del modelo) |
| **Falsos Negativos (FN)** | 0 | 0 |

> ***Nota sobre las Limitaciones del Sistema en Producción:** Los ceros absolutos en el motor determinista son un artefacto de hacer pruebas sobre PDFs sintéticos (nativos digitales). En el mundo real (al escalar a un dataset de 75,000 facturas escaneadas), los documentos estarán borrosos, arrugados o mal iluminados. Esto causará que el LLM se equivoque al leer los números (ej. confundir un 8 con un 3). Cuando el LLM extrae un número mal, la suma determinista en Python fallará, lo que levantará un **Falso Positivo**. Es decir: en producción, los fallos de lectura del LLM se transformarán invariablemente en alertas matemáticas. El ruteo mitiga esto mandando dichos casos a Revisión Manual.*

---

## 4. Capa Forense (Pixel-Level Tamper Detection)

Cotejo incluye una capa concurrente de análisis forense que no emite REJECT automático, sino que fuerza la revisión manual (`MANUAL_REVIEW`) apoyada en evidencias visuales (overlays).

- **Metadatos Estructurales**: Detección de actualizaciones incrementales y editores sospechosos (pikepdf/PyMuPDF).
- **Tipografía**: Inconsistencias calculadas por Mahalanobis (altura, grosor de trazo, densidad) en texto y OCR.
- **ELA y Ruido**: Error Level Analysis y Wavelet Residual para documentos escaneados.
- **Copy-Move**: Detección de clonaciones de píxeles vía keypoints AKAZE y DBSCAN.

### Limitaciones de la Capa Forense
1. **Manipulaciones Sintéticas**: Las manipulaciones de evaluación son sintéticas; un falsificador profesional que reimprime y reescanea el documento elimina la mayoría de las trazas de píxel (solo sobreviven typography y señales de contenido).
2. **Archivos Nativos**: ELA y noise no aplican a PDFs nativos; en ese dominio la cobertura recae en metadata y typography.
3. **Falsedad de Contenido**: El sistema detecta manipulación del ARCHIVO, no falsedad del CONTENIDO: una factura generada desde cero con datos falsos es forensemente impecable. Ese vector requiere reconciliación multi-documento.

### Métricas Forenses — benchmark realista v1 (Fase 1 de powerUp.md)

> **Nota de retractación metodológica (2026-06-11):** las métricas forenses que este README
> publicaba antes quedan retiradas. Contaban como detección cualquier alerta en la página (sin
> verificar que señalara la región manipulada), sin split calib/test, con umbrales ajustados
> sobre el mismo set reportado. Diagnóstico y plan completos en [powerUp.md](powerUp.md).

El **benchmark v1** somete 41 facturas reales (`mychen76/invoices-and-receipts_ocr_v1`) a un
grid de **5 ataques realistas guiados por OCR** (copia de dígito font-matched, reescritura con
fuente externa, borrado por inpainting, splice de otro documento, clonado de región) × **4
cadenas de transmisión** (original, recompresión, WhatsApp, print-scan). Cada ataque cae sobre
contenido real con una máscara ground-truth exacta. Un ataque cuenta como **localizado** solo si
el módulo objetivo emite un hallazgo con IoU ≥ 0.2 contra esa máscara. Split test (n=480):

**APCER localizado** (% de ataques cuya región NO es señalada — menor es mejor):

| ataque | original | recompresión | whatsapp | print-scan |
|---|---|---|---|---|
| todos los ataques | **100** | **100** | **100** | **100** |

**APCER a nivel página** (% que ni siquiera dispara una alerta en la página) y **BPCER**
(falsas alarmas en documentos limpios):

| módulo | APCER pág. (rango) | BPCER (rango) |
|---|---|---|
| typography | 20–35% | 55–75% |
| ela_noise | 30–100% | 0–75% |
| copy_move | 100% (silencio total) | 0% |

*Lectura honesta:* **la capa forense clásica no localiza fraude en facturas reales** (APCER
localizado = 100% en todo el grid). Las alertas de página de typography/ela_noise disparan en
~70% de documentos manipulados pero también en 55–75% de los limpios: son indistinguibles de
ruido, no señal. La transmisión rompe los detectores de dos formas opuestas — WhatsApp apaga
ela_noise por completo (silencio), las demás cadenas lo dejan disparando en todas partes — y
copy_move con coherencia ±2px no detecta nada tras la recompresión JPEG. Este es el resultado
de partida del proyecto: los detectores individuales no bastan; el trabajo es construir, sobre
baselines aprendidos y fusión calibrada, una decisión de auditoría con garantías (Fases 2–3 de
[powerUp.md](powerUp.md)).

Reproducir (los ~960 artefactos de imagen no se versionan por tamaño; se regeneran con semillas
fijas):
```bash
python eval/build_benchmark.py --base_dir data/hf_eval --out_dir data/benchmark_v1
python eval/eval_benchmark.py  --bench_dir data/benchmark_v1 --split test
```

---

## 5. Interfaz de Usuario y Ruteo

La interfaz web rutea los resultados demostrando el origen del dato (Página del PDF) y aplicando los colores de la política de decisión, incluyendo un **Panel Forense** para evaluar visualmente las alertas de fraude a nivel de píxel:


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

## 5. Tecnologías y Despliegue Local

- **API:** Python 3.12, FastAPI, Pydantic v2.
- **Modelos:** Google GenAI SDK (Gemini 2.5 Flash / Pro).
- **Procesamiento de PDF:** PyMuPDF.

**Ejecución:**
```bash
pip install -r requirements.txt
# Configurar GEMINI_API_KEY en archivo .env
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```
