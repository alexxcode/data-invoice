# Instructivo: Capa Forense de Documentos (Pixel-Level Tamper Detection) para Cotejo

**Audiencia:** ingenieros y agentes de código que van a implementar esta capa sobre el repositorio `alexxcode/data-invoice`.
**Estado del repo asumido:** pipeline de 3 fases (Extracción VLM → Motor Determinista `app/rules.py` → Análisis Semántico), orquestado por `app/agent.py`, con rasterización vía PyMuPDF a 150 DPI.

---

## 0. Principio rector (leer antes de escribir código)

Cotejo hoy audita **los números** de la factura. Esta capa audita **los píxeles y la estructura del archivo**. El objetivo es detectar manipulación del documento (montos editados, regiones clonadas, splicing, re-guardados sospechosos) que el motor determinista no puede ver porque el fraude competente tiene aritmética consistente.

Reglas de diseño no negociables, coherentes con la filosofía actual del repo:

1. **La capa forense NUNCA emite `REJECT` por sí sola.** Toda técnica forense tiene tasa de falsos positivos no nula. El hallazgo forense emite `FORENSIC_ALERT` y fuerza `MANUAL_REVIEW`, igual que el análisis semántico. La autoridad de rechazo sigue siendo exclusiva del motor determinista.
2. **Cada alerta debe venir con evidencia visual** (heatmap o overlay PNG) y una explicación legible por el revisor humano. Una alerta sin evidencia renderizable no se emite.
3. **Separación por tipo de documento.** Las técnicas de píxeles aplican a documentos rasterizados (scans, fotos, imágenes embebidas). Para PDFs nativos digitales la señal está en la estructura y metadatos del archivo, no en los píxeles. El pipeline debe ramificar primero (ver §2).

---

## 1. Estructura de módulos a crear

```
app/
  forensics/
    __init__.py
    models.py          # Pydantic: ForensicReport, ForensicFinding, DocumentClass
    classifier.py      # Clasifica: NATIVE_DIGITAL | SCANNED | HYBRID
    metadata.py        # Forense estructural del PDF (no requiere píxeles)
    ela.py             # Error Level Analysis
    copy_move.py       # Detección de regiones clonadas (keypoints)
    noise.py           # Inconsistencia de ruido por bloques
    typography.py      # Consistencia tipográfica en regiones de texto
    scorer.py          # Agregación de hallazgos → ForensicReport
    overlays.py        # Generación de evidencia visual (PNG)
eval/
  tamper_injector.py   # Generador de dataset manipulado (ground truth)
  eval_forensics.py    # Métricas de detección (AUC, APCER/BPCER)
```

Dependencias nuevas en `requirements.txt`:

```
opencv-python-headless>=4.9
scikit-image>=0.22
scipy>=1.11
Pillow>=10.0
```

No se requiere GPU. Todo corre en CPU y es paralelizable con la llamada al VLM (la capa forense no depende de la salida de Gemini).

---

## 2. `classifier.py`: ramificación por tipo de documento

Implementar `classify_document(doc: fitz.Document) -> DocumentClass` con esta lógica:

```python
from enum import Enum

class DocumentClass(str, Enum):
    NATIVE_DIGITAL = "native_digital"   # texto vectorial, generado por software
    SCANNED = "scanned"                 # página = una imagen grande
    HYBRID = "hybrid"                   # mezcla (típico de PDFs editados)

def classify_document(doc):
    text_chars = sum(len(p.get_text()) for p in doc)
    image_area_ratio = max_image_coverage(doc)  # área de imágenes / área de página
    if text_chars > 200 and image_area_ratio < 0.5:
        return DocumentClass.NATIVE_DIGITAL
    if text_chars < 50 and image_area_ratio > 0.9:
        return DocumentClass.SCANNED
    return DocumentClass.HYBRID
```

Ruteo de técnicas según clase:

| Técnica | NATIVE_DIGITAL | SCANNED | HYBRID |
|---|---|---|---|
| metadata.py (estructural) | ✅ señal principal | ✅ | ✅ |
| ela.py | ❌ (FP garantizado) | ✅ solo si imagen fuente es JPEG | ✅ por región |
| copy_move.py | ⚠️ opcional (logos repetidos = FP) | ✅ | ✅ |
| noise.py | ❌ | ✅ | ✅ por región |
| typography.py | ✅ (vía text layer) | ✅ (vía OCR boxes) | ✅ |

**Por qué esto importa:** ejecutar ELA sobre un PDF nativo renderizado produce mapas uniformes o ruido sin significado y genera falsos positivos sistemáticos. Un agente de código que ignore esta tabla va a producir una capa forense que alerta sobre todo y no sirve para nada.

---

## 3. `metadata.py`: forense estructural (implementar PRIMERO)

Es la técnica más barata y con mejor relación señal/costo. No toca píxeles. Con PyMuPDF:

### 3.1 Señales a extraer

1. **Actualizaciones incrementales.** Un PDF editado después de su creación suele guardarse con incremental updates (múltiples `%%EOF`). Detectar:
   ```python
   raw = open(path, "rb").read()
   n_eof = raw.count(b"%%EOF")
   # n_eof > 1 → el archivo fue modificado tras su generación original
   ```
2. **Discrepancia de fechas.** `doc.metadata["creationDate"]` vs `modDate`. Una factura legítima rara vez se modifica días después de creada. Diferencia > 0 → finding de severidad baja; diferencia > 24h → media.
3. **Software productor.** `doc.metadata["producer"]` y `creator`. Buscar trazas de editores de imagen/PDF interactivos: `Photoshop`, `GIMP`, `Illustrator`, `iLovePDF`, `Sejda`, `PDFescape`, `Canva`. Una factura de utility generada por `Adobe Photoshop` es una bandera roja directa. Mantener la lista en un YAML configurable, no hardcodeada.
4. **XMP huérfano.** Extraer el stream XMP (`doc.xref_xml_metadata()`) y buscar `xmpMM:History` con acciones `saved`/`edited` posteriores a la creación, y `photoshop:` namespaces.
5. **Texto superpuesto.** Para cada página, obtener bloques de texto con `page.get_text("dict")` y detectar bounding boxes de spans que se solapan con IoU > 0.3. Texto encima de texto es el patrón clásico de "tapar y reescribir el monto".
6. **Fuentes anómalas.** Listar fuentes embebidas por página (`page.get_fonts()`). Si una página usa una fuente que aparece UNA sola vez en todo el documento y está en un span que contiene dígitos, marcar el span (un monto reescrito con otra herramienta casi nunca embebe la misma fuente con el mismo subset).

### 3.2 Salida

Cada señal produce un `ForensicFinding` (ver §7) con severidad `LOW | MEDIUM | HIGH` y, cuando aplique, el bbox de la región implicada para el overlay.

---

## 4. `ela.py`: Error Level Analysis

**Teoría en dos líneas:** al recomprimir un JPEG, las regiones que ya fueron comprimidas con los mismos parámetros cambian poco; las regiones editadas/pegadas después cambian más. El mapa de diferencias revela regiones con historial de compresión distinto.

**Aplicabilidad:** SOLO sobre imágenes fuente JPEG embebidas en el PDF (scans). Extraerlas directamente, NO sobre el render de PyMuPDF:

```python
for img in page.get_images(full=True):
    xref = img[0]
    base = doc.extract_image(xref)
    if base["ext"] in ("jpeg", "jpg"):
        run_ela(base["image"])  # bytes originales, sin re-render
```

**Implementación:**

```python
from PIL import Image, ImageChops
import io, numpy as np

def run_ela(jpeg_bytes: bytes, quality: int = 90) -> np.ndarray:
    original = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    buf = io.BytesIO()
    original.save(buf, "JPEG", quality=quality)
    recompressed = Image.open(buf)
    diff = ImageChops.difference(original, recompressed)
    ela = np.asarray(diff).astype(np.float32).max(axis=2)  # canal máx
    return ela
```

**Decisión (no usar umbral global ingenuo):**

1. Normalizar `ela` por el percentil 99 de la imagen.
2. Dividir en bloques de 32×32 px. Calcular media por bloque.
3. Calcular z-score de cada bloque contra la distribución de bloques de la misma imagen.
4. Bloques con z > 3.0 que formen un componente conexo de área > 0.1% de la página → candidato.
5. **Filtro crítico de FP:** descartar componentes que coincidan con bordes de alto contraste (texto negro sobre blanco genera ELA alto de forma natural). Hacerlo con una máscara de bordes (Canny dilatado): solo cuentan los bloques anómalos cuya energía NO se explica por la máscara de bordes.
6. Si el candidato se solapa con un bbox que contiene dígitos (cruzar contra las posiciones de texto/OCR), elevar severidad a `HIGH`.

Guardar el heatmap coloreado (colormap `inferno`) como overlay con alpha 0.45 sobre la página original.

---

## 5. `copy_move.py`: regiones clonadas

**Caso de uso real:** clonar un bloque de fondo limpio para tapar un cargo, o duplicar un dígito (convertir 1.250 en 1.255 copiando el "5").

**Implementación basada en keypoints (robusta a escala/rotación leve):**

1. Convertir página a escala de grises (el render de 150 DPI existente sirve aquí).
2. Detectar keypoints + descriptores con ORB (`nfeatures=5000`) o, mejor para texto, AKAZE.
3. Matchear descriptores **de la imagen contra sí misma** con BFMatcher + ratio test de Lowe (0.75), descartando matches cuya distancia espacial sea < 40 px (auto-matches triviales).
4. Agrupar los vectores de desplazamiento (dx, dy) de los pares restantes con DBSCAN (`eps=8`, `min_samples=6`). Un cluster denso = un conjunto de puntos que se repite desplazado coherentemente = región clonada.
5. **Filtros de FP obligatorios para facturas:**
   - Excluir matches dentro de regiones de logo (las facturas repiten logos/iconos legítimamente). Heurística: si ambos extremos del match caen en el 15% superior de la página, descartar.
   - Excluir matches entre caracteres idénticos en posiciones de texto distintas (en un documento, la letra "a" aparece cientos de veces). Para esto exigir que el cluster tenga ≥ 6 matches con el MISMO vector de desplazamiento (±2 px): el texto natural repetido no produce desplazamientos coherentes, el clonado sí.
6. Overlay: dibujar líneas entre pares del cluster y los dos bboxes convexos implicados.

Severidad: `MEDIUM` por defecto; `HIGH` si alguno de los bboxes se solapa con la zona de totales/importes (cruzar contra los bboxes que la Fase 1 ya extrae o contra OCR de dígitos).

---

## 6. `noise.py`: inconsistencia de ruido

**Teoría:** cada sensor/escáner deja una firma de ruido aproximadamente uniforme en todo el documento. Una región pegada desde otro documento trae OTRO ruido. Detectable midiendo varianza local del ruido residual.

**Implementación (wavelet residual, scikit-image):**

```python
from skimage.restoration import estimate_sigma, denoise_wavelet
import numpy as np

def noise_map(gray: np.ndarray, block: int = 64) -> np.ndarray:
    den = denoise_wavelet(gray, channel_axis=None, rescale_sigma=True)
    residual = gray.astype(np.float32) - den.astype(np.float32)
    h, w = residual.shape
    out = np.zeros((h // block, w // block))
    for i in range(out.shape[0]):
        for j in range(out.shape[1]):
            out[i, j] = residual[i*block:(i+1)*block, j*block:(j+1)*block].std()
    return out
```

Decisión: igual esquema de z-score por bloque + componente conexo que en ELA, con el mismo filtro de máscara de bordes (el texto inyecta varianza que no es ruido de sensor). **Solo aplicar a `SCANNED`**: en renders de PDFs nativos el ruido es cero y cualquier región con antialiasing distinto dispara falsas alarmas.

---

## 7. `typography.py`: consistencia tipográfica de los dígitos

La manipulación más común en facturas es reescribir un monto. El monto reescrito casi nunca calza perfectamente en altura, grosor de trazo, baseline y espaciado con el resto del documento.

**Pipeline:**

1. Obtener bboxes de tokens numéricos:
   - `NATIVE_DIGITAL`: `page.get_text("dict")`, filtrar spans con regex `[\d.,]{2,}`.
   - `SCANNED`: OCR con Tesseract (`pytesseract.image_to_data`) sobre el render a 300 DPI (subir DPI solo para esta etapa), filtrar el mismo regex.
2. Para cada token, recortar el crop y calcular features:
   - Altura de caja normalizada por la mediana de la línea.
   - Grosor de trazo: `stroke_width = 2 * area_tinta / perimetro` sobre el crop binarizado (Otsu).
   - Offset de baseline respecto a la línea de texto contenedora.
   - Densidad de tinta (ratio píxeles negros).
3. Construir la distribución de features de TODOS los tokens numéricos del documento. Calcular distancia de Mahalanobis de cada token contra esa distribución.
4. Tokens con distancia > umbral (calibrar en eval, punto de partida: chi² al 99.5%) → finding. Severidad `HIGH` si el token está en la fila de Total/Subtotal/Impuestos (Cotejo ya sabe dónde están: usar los campos que devolvió la Fase 1 y matchear por valor o por posición).

**Ventaja clave de esta técnica:** funciona también en `NATIVE_DIGITAL` (donde ELA y noise no aplican) y ataca directamente el vector de fraude más probable del dominio.

---

## 8. `models.py` y `scorer.py`: contrato de datos y agregación

```python
from pydantic import BaseModel
from enum import Enum

class Severity(str, Enum):
    LOW = "low"; MEDIUM = "medium"; HIGH = "high"

class ForensicFinding(BaseModel):
    technique: str                # "ela" | "copy_move" | "noise" | "typography" | "metadata"
    severity: Severity
    page: int
    bbox: tuple[float, float, float, float] | None
    score: float                  # 0..1, intra-técnica
    explanation: str              # texto para el revisor humano
    overlay_path: str | None      # PNG de evidencia

class ForensicReport(BaseModel):
    document_class: DocumentClass
    findings: list[ForensicFinding]
    forensic_risk: float          # 0..1 agregado
    requires_review: bool
```

**Agregación en `scorer.py` (mantenerla simple y auditable, NO un modelo entrenado en v1):**

- `forensic_risk = 1 - Π(1 - w_t * score_i)` sobre findings, con pesos por técnica configurables en YAML (`metadata: 0.9`, `typography: 0.85`, `copy_move: 0.7`, `ela: 0.6`, `noise: 0.5`). Los pesos reflejan confiabilidad relativa de cada técnica, se calibran en §10.
- `requires_review = (cualquier finding HIGH) or (forensic_risk > umbral_yaml)`.
- Regla de refuerzo cruzado: si dos técnicas independientes marcan bboxes con IoU > 0.3, duplicar el peso efectivo de ese hallazgo y fijar severidad `HIGH`. La coincidencia espacial entre técnicas independientes es la señal más fuerte de todo el sistema.

---

## 9. Integración en `agent.py` y políticas de ruteo

1. **Paralelismo:** lanzar la capa forense concurrentemente con la llamada al VLM (asyncio + `run_in_executor` para el trabajo CPU-bound, o Celery si ya está en el stack). La forense no depende de Gemini; solo `typography.py` mejora si recibe los bboxes de la Fase 1, así que ejecutarla en dos pasadas: técnicas independientes en paralelo, typography al cierre.
2. **Nueva política de ruteo (extiende la tabla actual, no la reemplaza):**

```
🔴 REJECT          → (sin cambios) solo motor determinista o Score < 0.60
🟡 MANUAL_REVIEW   → condiciones actuales  OR  forensic_report.requires_review
🟢 AUTO_APPROVE    → condiciones actuales  AND  forensic_risk < umbral_auto (default 0.25)
```

3. **Persistencia:** el `ForensicReport` completo se serializa junto al resultado de auditoría. Los overlays se guardan en el mismo storage que las páginas renderizadas.

---

## 10. UI: evidencia para el revisor

En la vista de `MANUAL_REVIEW` agregar un panel "Forense" que muestre:

- Lista de findings ordenada por severidad, cada uno con su `explanation`.
- Toggle por técnica que superpone el overlay PNG correspondiente sobre la página (misma mecánica que ya usa la UI para señalar el origen del dato).
- Badge de `forensic_risk` con el desglose por técnica.

Sin esto, la capa es una caja negra y el revisor humano la va a ignorar. La evidencia visual ES el producto.

---

## 11. Evaluación: `eval/tamper_injector.py` y métricas

No se puede afirmar nada sin un dataset con ground truth. Construirlo sintéticamente, igual que el inyector de anomalías existente pero a nivel de píxel:

### 11.1 Inyector de manipulaciones

Sobre el corpus de PDFs limpios actual, generar variantes manipuladas con etiqueta y máscara:

1. **digit_swap:** rasterizar, localizar un dígito de un importe (OCR), reemplazar su crop por el crop de otro dígito del mismo documento (esto simula copy-move real) o por un dígito renderizado con fuente similar (simula reescritura). Guardar máscara binaria de la región alterada.
2. **region_patch:** pegar un parche de fondo limpio sobre una línea de cargo.
3. **splice:** insertar un bloque (sello, firma, línea de detalle) proveniente de OTRO documento del corpus.
4. **resave_chain:** abrir y reguardar con calidades JPEG distintas para simular historial de edición.
5. Para la rama estructural: editar un PDF nativo con `pikepdf` provocando incremental update y metadata de editor.

Cada muestra emite `{path, tamper_type, page, mask_path}`. Generar también el mismo número de muestras limpias re-procesadas (negativos duros: re-escaneadas/recomprimidas SIN manipular) para medir FP realistas.

### 11.2 Métricas (reutilizar el marco de Vivace)

Tratarlo como un problema PAD, mismo lenguaje que ISO 30107-3:

- **APCER** (ataques no detectados) y **BPCER** (documentos legítimos alertados) por tipo de manipulación y por técnica.
- Curva ROC del `forensic_risk` agregado y AUC global.
- **Métrica de localización:** IoU entre los bboxes de findings y la máscara ground truth (un detector que alerta la página entera no sirve; exigir IoU > 0.2 para contar como hit localizado).
- Reportar todo en una tabla en el README con n explícito y la misma honestidad metodológica que la tabla actual (incluir la nota de que las manipulaciones son sintéticas y que el fraude real puede ser más sutil).

### 11.3 Calibración de umbrales

Los umbrales de §4–§8 (z-scores, pesos, `umbral_auto`) se fijan sobre un split de calibración (50% del dataset sintético) optimizando: BPCER ≤ 5% como restricción dura, maximizando 1−APCER. El split restante reporta las métricas finales. Documentar los valores elegidos en el YAML de configuración con un comentario que indique de qué corrida de calibración salieron.

---

## 12. Orden de implementación y criterios de aceptación

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 1 | `classifier.py` + `models.py` | Clasifica correctamente 20 docs de prueba (manual) en las 3 clases |
| 2 | `metadata.py` | Detecta incremental update, editor sospechoso y texto solapado en casos construidos a mano con `pikepdf` |
| 3 | `tamper_injector.py` | Genera ≥ 200 muestras manipuladas + 200 negativos duros con máscaras |
| 4 | `typography.py` | Sobre el dataset: detecta digit_swap con APCER < 30% y BPCER < 5% |
| 5 | `ela.py` + `noise.py` | Sobre scans del dataset: detección de region_patch/splice, BPCER < 5% |
| 6 | `copy_move.py` | Detecta region_patch clonado; cero alertas en los 200 negativos por logos/texto repetido |
| 7 | `scorer.py` + integración `agent.py` | Pipeline end-to-end: doc manipulado → MANUAL_REVIEW con overlay visible; doc limpio → ruteo sin cambios |
| 8 | UI + README | Panel forense funcional; tabla de métricas APCER/BPCER publicada |

Notas para el agente de código:

- No optimizar rendimiento antes del paso 7. Primero correcto, después rápido.
- Cada técnica debe poder ejecutarse y testearse de forma aislada (`python -m app.forensics.ela ruta.pdf`).
- Los falsos positivos matan este feature. Ante la duda entre sensibilidad y especificidad, elegir especificidad: una técnica que alerta de más será desactivada por configuración y el esfuerzo se pierde.
- Mantener TODOS los umbrales y pesos en un único `app/forensics/config.yaml`. Nada de números mágicos en el código.

---

## 13. Limitaciones a declarar en el README (honestidad metodológica)

1. Las manipulaciones de evaluación son sintéticas; un falsificador profesional que reimprime y reescanea el documento elimina la mayoría de las trazas de píxel (solo sobreviven typography y señales de contenido).
2. ELA y noise no aplican a PDFs nativos; en ese dominio la cobertura recae en metadata y typography.
3. El sistema detecta manipulación del ARCHIVO, no falsedad del CONTENIDO: una factura generada desde cero con datos falsos es forensemente impecable. Ese vector requiere la capa de reconciliación multi-documento (roadmap).
