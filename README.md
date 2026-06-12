# Cotejo — Auditoría forense de facturas con ruteo de decisión garantizado

Cotejo es un sistema de auditoría de facturas que combina extracción multimodal, reglas
deterministas y análisis forense, y los fusiona en una **decisión de ruteo a nivel documento con
una garantía estadística sobre la fuga de fraude**. Más que "leer una factura", responde la
pregunta operativa: *¿qué fracción del volumen puedo automatizar sin que se cuele fraude, y con
qué cobertura demostrable?*

El proyecto es también un estudio empírico honesto: documenta **qué detectores de manipulación
NO funcionan** sobre facturas reales transmitidas por canales del mundo real (recompresión,
WhatsApp, print-scan), y muestra cómo recuperar valor combinando señales débiles bajo una cota
conformal.

> **Premisa de diseño:** los LLMs alucinan y todo detector forense tiene falsos positivos no
> nulos. Por eso la autoridad de **rechazo** es exclusiva del motor determinista; las capas
> probabilísticas (forense, VLM) solo **derivan a revisión humana**. Una detección fallida nunca
> produce un pago indebido automático salvo a través del ruteo de auto-aprobación, cuyo riesgo
> está acotado por la garantía conformal.

---

## Resultados en una mirada

Evaluado sobre un benchmark propio de manipulaciones realistas × canales de transmisión
(960 muestras; ver [datasheet](data/benchmark_v1/DATASHEET.md)), split test:

| Hallazgo | Evidencia |
|---|---|
| **El forense clásico no localiza fraude en facturas reales** | APCER localizado = **100%** en todo ataque × canal; falsas alarmas 55–75% (ELA/ruido/tipografía) — indistinguible de ruido. |
| **Un VLM de propósito general no localiza, pero detecta a nivel documento con muy bajo FP** | BPCER **6–18%** (vs 55–75% del clásico); AUC ≈ **0.70**. |
| **La fusión calibrada supera a cualquier señal sola** | AUC: clásico ≈ **0.5** (ruido) · VLM **0.70** · **fusión 0.73**. Las señales clásicas, inútiles por separado, suman al calibrarse. |
| **El ruteo conformal automatiza con fuga acotada y demostrable** | A prevalencia real (2%): **~66–79% de automatización con ~1.1% de fuga** de fraude; o cobertura certificada con garantía ≤5% de escape al 90% de confianza. |

*(Números del split test, n≈195 (~86% del benchmark); reproducibles con
`python reproduce.py --skip-vlm`. El registro completo por fase está en [powerUp.md](powerUp.md).)*

---

## 1. El problema y la tesis

Revisar facturas a mano es lento; la extracción (OCR/parsing) ya es commodity. Lo que sigue
siendo trabajo humano es el **juicio**: detectar que un total no cuadra, que una factura está
duplicada, que un monto fue reescrito — y decidir qué se aprueba solo y qué necesita un humano.

Detectar manipulación documental con técnicas forenses clásicas (ELA, copy-move, ruido) es un
área madura, pero su fragilidad ante recompresión está documentada. Cotejo parte de esa hipótesis
y la **mide en el dominio de facturas reales**, llegando a una tesis constructiva:

> Ningún detector forense individual sobrevive a las condiciones reales de transmisión de
> facturas. Pero la **fusión calibrada de señales débiles e independientes** (píxel + estructura
> + tipografía + razonamiento VLM + aritmética determinista), con **ruteo selectivo conformal**,
> permite automatizar una fracción grande del volumen con una **cota estadística demostrable** de
> fuga de fraude.

---

## 2. Arquitectura

```
[PDF / imagen]
     │
     ▼
(1) Extracción VLM        Gemini (multimodal) → JSON estructurado + provenance {doc, página, campo}
     │
     ▼
(2) Motor determinista    aritmética, duplicados, campos faltantes/ inválidos
     │                    ÚNICA capa con autoridad de RECHAZO (no alucina)
     ▼
(3) Capa forense          metadata + tipografía + ELA + ruido + copy-move (a nivel píxel/archivo)
     │                    solo DERIVA a revisión, nunca rechaza
     ▼
(4) Fusión + ruteo        combina señales → P(manipulado) calibrada → decisión con garantía conformal
     │
     ▼
[Informe auditable: decisión + citas + evidencia visual]
```

**Principio de groundedness:** las cifras y citas del informe provienen de la salida
estructurada verificada y de las herramientas deterministas, no del texto libre del LLM. El LLM
razona y redacta; no es la fuente de verdad de los números.

### Política de ruteo
- **🔴 REJECT** — solo motor determinista (fraude aritmético, campos obligatorios, duplicado).
- **🟡 MANUAL_REVIEW** — alerta forense/VLM, o confianza intermedia.
- **🟢 AUTO_APPROVE** — limpio y por debajo del umbral conformal de riesgo.

---

## 3. Threat model

Las métricas de detección no son interpretables sin declarar contra quién y bajo qué canal se
miden. El modelo de amenaza completo está en **[THREAT_MODEL.md](THREAT_MODEL.md)**. En resumen:

| Adversario | Capacidad | Cobertura en Cotejo |
|---|---|---|
| **Casual** | edita un dígito y reenvía | determinista (si rompe la suma) + forense (si sobrevive el canal) + VLM |
| **Competente** | reimprime/reescanea, aritmética consistente | VLM (incoherencia residual); el forense clásico **falla aquí** |
| **Fabricador** | factura falsa coherente desde cero | **fuera de alcance**: requiere reconciliación externa (roadmap) |

El **canal de transmisión** (original / recompresión / WhatsApp / print-scan) es parte del modelo:
decide la viabilidad de cada detector. Fuera de alcance explícito: fabricación de contenido,
adversario adaptativo, y localización a nivel píxel (problema abierto).

---

## 4. El benchmark

Para medir sin "tablas de promesas", se construyó un benchmark de manipulaciones **realistas**
sobre 41 facturas reales (`mychen76/invoices-and-receipts_ocr_v1`), cruzando:

- **5 ataques guiados por OCR sobre contenido real** (no parches aleatorios): copia de dígito
  font-matched, reescritura con fuente externa, borrado por inpainting, splice de otro documento,
  clonado de región. Cada uno con máscara ground-truth exacta.
- **4 canales de transmisión:** original, recompresión JPEG, WhatsApp (≤1280px + q70), print-scan.

960 muestras, splits calib/test por documento, generación semillada y reproducible. Detalle y
sesgos conocidos en el **[datasheet](data/benchmark_v1/DATASHEET.md)**. Métrica de localización:
un ataque cuenta como detectado solo si un hallazgo solapa la región real (IoU ≥ 0.2).

---

## 5. Resultados

### 5.1 Stack forense clásico — resultado negativo (honesto)

APCER localizado por ataque × canal (% de ataques cuya región **no** se señala; menor = mejor):

| | original | recompresión | whatsapp | print-scan |
|---|---|---|---|---|
| **todos los ataques** | ~100 | ~100 | ~100 | ~100 |

BPCER (falsas alarmas en limpios): typography 55–75% · ELA/ruido 0–75% · copy-move 0% (silencio
total). **Lectura:** la capa forense clásica no localiza ninguna manipulación; sus alertas de
página son indistinguibles de ruido. La transmisión rompe los detectores de dos formas opuestas:
WhatsApp apaga ELA/ruido por completo, las demás cadenas lo dejan disparando en todas partes.

> Nota de retractación metodológica: versiones previas de este README publicaban métricas
> forenses favorables (p. ej. "typography 50/45") que eran artefactos de un scoring a nivel
> página sin localización, sin split, y con umbrales ajustados sobre el set reportado. Esas
> cifras quedan retiradas.

### 5.2 VLM-as-judge — detecta a nivel documento, no localiza

Gemini como perito forense (`eval/vlm_judge.py`) tampoco localiza el píxel (razona sobre la
incoherencia visible/aritmética, no sobre la textura), pero a nivel documento es un detector
**útil y de bajo falso positivo**: BPCER 6–18% frente al 55–75% del stack clásico, capturando
mejor el vector de fraude más probable (reescritura de importe — APCER de página 17–29%).
AUC ≈ 0.70.

### 5.3 Fusión calibrada + ruteo conformal — el resultado

Una regresión logística calibrada combina las señales clásicas (débiles) con el VLM
(`eval/fusion_routing.py`):

| modelo | AUC (test) |
|---|---|
| clásico solo | ≈0.5 (ruido) |
| VLM solo | 0.70 |
| **fusión clásico+VLM** | **0.73** |

La fusión supera a cualquier señal sola: las señales clásicas, inservibles por separado,
**aportan al calibrarse**.

El ruteo es **predicción selectiva conformal**: la garantía se fija sobre la clase de fraude
(qué fracción del fraude se cuela en AUTO_APPROVE), por lo que es **independiente de la
prevalencia** y transfiere a cualquier despliegue. Reproyectada a prevalencia real de cliente
(2% manipuladas), la curva riesgo-cobertura (test):

| automatización | fuga en auto-approve | fraude capturado |
|---|---|---|
| 53% | 1.0% | 74% |
| 66% | 1.1% | 65% |
| 79% | 1.1% | 55% |

**Titular:** automatizar ~2 de cada 3 facturas con ~1% de fuga de fraude en lo auto-aprobado, y
una cota conformal demostrable (≤5% de escape al 90% de confianza, certificada sobre ~10% del
volumen con la calibración actual). La cobertura certificada crece con más datos de calibración
(la cota Clopper-Pearson es conservadora con calib pequeño — comportamiento correcto, no un fallo).

---

## 6. Limitaciones honestas

- **Manipulaciones sintéticas ≠ fraude de campo.** El benchmark inyecta ataques realistas sobre
  facturas reales, pero no demuestra generalización a fraude sofisticado real.
- **Sin localización.** Ni el clásico ni un VLM general localizan la región manipulada en
  facturas transmitidas. Queda como problema abierto (candidatos: detectores aprendidos tipo
  TruFor/CAT-Net en inferencia).
- **Detecta manipulación del documento, no falsedad del contenido.** Una factura falsa coherente
  desde cero es forensemente impecable; requiere reconciliación contra fuente externa.
- **Prevalencia.** El benchmark está saturado de ataques a propósito; los titulares se
  reproyectan a la prevalencia real y la garantía se fija sobre la clase de fraude para ser
  robusta a la mezcla.
- **Extracción (O1) aún no medida** contra el dataset etiquetado IDSEM (ver roadmap).

---

## 7. Reproducción

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -q                                   # suite de tests

# Pipeline experimental completo (sin llaves ni coste; usa caché VLM si existe):
python reproduce.py --skip-vlm

# Con el baseline VLM vía Vertex AI (consume billing GCP, sin límite de free tier):
VLM_USE_VERTEX=1 GOOGLE_CLOUD_PROJECT=<tu-proyecto> python reproduce.py
```

Etapas individuales: `build_benchmark.py` → `eval_benchmark.py` (clásico) → `eval_vlm.py` (VLM)
→ `fusion_routing.py` (fusión + ruteo). Todo idempotente y semillado.

---

## 8. Stack y despliegue

- **API:** Python 3.12, FastAPI, Pydantic v2. **PDF:** PyMuPDF. **Forense:** OpenCV, scikit-image,
  scikit-learn, Tesseract. **Modelos:** Gemini (Flash/Pro) vía Google GenAI SDK (AI Studio o
  Vertex AI). **Cola opcional:** Celery + Redis (en local corre síncrono sin Redis).
- **Despliegue:** contenedor en Cloud Run.

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload   # GEMINI_API_KEY en .env
```

### Interfaz

La UI rutea los resultados con la política de decisión y un panel forense con la evidencia
visual (overlays) sobre la página de origen.

<div align="center">
  <img src="imagenes_repo/Screenshot%202026-06-08%20225846.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20232503.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-08%20234921.png" width="45%" />
  <img src="imagenes_repo/Screenshot%202026-06-09%20000218.png" width="45%" />
</div>

---

## 9. Roadmap

1. **Localización aprendida** — TruFor/CAT-Net en inferencia sobre el benchmark; ¿alguno baja del
   100% de APCER localizado?
2. **Extracción medida (O1)** — exactitud por campo contra IDSEM (75k facturas etiquetadas,
   CC-BY 4.0); cierra la mitad "extracción" del pipeline.
3. **Reconciliación multi-documento** — el vector del adversario fabricador (A3 del threat model).
4. **Publicación del benchmark** en HuggingFace Hub con su datasheet.
