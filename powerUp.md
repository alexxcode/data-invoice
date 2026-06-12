# powerUp.md — Plan para convertir Cotejo en un trabajo de investigación serio

> Documento de planificación y registro. Define el diagnóstico del estado actual, la tesis de
> investigación, los pilares del trabajo, el moat comercial y las fases de ejecución con
> criterios de aceptación. Se actualiza al cierre de cada fase con resultados reales.
>
> Fecha de creación: 2026-06-11. Estado: **Fases 0 y 1 completadas (2026-06-11).
> Siguiente: Fase 2 (baselines aprendidos — prioridad elevada, ver §5).**

---

## 1. Diagnóstico del estado actual (por qué los resultados son mediocres)

### 1.1 Evaluación determinista circular
- El motor determinista reporta P=1.00 / R=1.00 (n=84) sobre PDFs sintéticos triviales generados
  por el mismo proyecto (`data/inject_anomalies.py`). El "fraude" es imprimir `total * 1.3` y la
  "detección" es verificar `subtotal + impuestos != total`. El resultado es un artefacto del
  diseño, no una medición.
- El objetivo O1 original (exactitud de extracción por campo contra las etiquetas de IDSEM,
  86 campos) **nunca se midió**. Era la única métrica de extracción con valor.

### 1.2 Evaluación forense contaminada por ajuste al test (Goodhart)
Evidencia encontrada en el código:

| # | Evidencia | Efecto |
|---|---|---|
| 1 | `tamper_injector.py` (clone): *"Select source from middle of page to avoid top 15% logo filter"* — el ataque se diseñó para esquivar el filtro anti-FP del detector | APCER no mide capacidad real |
| 2 | `ela.py`: filtro de bordes (anti-FP exigido por el spec §4.5) calculado y luego **ignorado** (*"Bypass edge filter because synthetic JPEG blocks trigger Canny"*) | Explica el BPCER de 100% |
| 3 | Cambio sin commitear que relaja la coherencia de copy_move de ±2px a ±8px; config ya aflojada vs spec (ratio_test 0.95 vs 0.75, eps 20 vs 8, min_samples 4 vs 6) | Knobs girados persiguiendo la métrica; aun así APCER 100% |
| 4 | `inject_digit_swap` pega un bloque aleatorio de 15×20px en posición aleatoria — **no toca dígitos**; puede caer fondo-sobre-fondo (indetectable por principio) | APCER de typography (50%) no es interpretable |
| 5 | El eval cuenta "hit" si el módulo dispara en cualquier parte de la página; las máscaras GT se generan pero **no se usan** (spec §11.2 exigía IoU > 0.2) | TPs posiblemente coincidentes con falsas alarmas |
| 6 | Sin split calibración/test (spec §11.3): umbrales ajustados sobre los mismos datos reportados | Números no generalizables |

### 1.3 Bugs metodológicos en los detectores
- `typography.py`: ruido aleatorio **sin semilla** sumado a las features → detector no determinista
  (dos corridas, resultados distintos). `baseline_offset` calculado contra `line["dir"]` (vector de
  dirección de escritura en PyMuPDF, no la baseline) → feature de ruido. Todo finding es HIGH.
- Espacios de coordenadas incompatibles: typography nativo emite bboxes en puntos PDF,
  copy_move en píxeles a 150 dpi, OCR divide por 2 (300→150 dpi). El refuerzo cruzado por IoU del
  `scorer.py` (declarado "la señal más fuerte del sistema") y los overlays (que asumen puntos)
  comparan espacios distintos → la regla nunca opera correctamente.
- ELA y noise no emiten bbox → no pueden participar del refuerzo cruzado ni localizarse en overlay.
- `metadata.py`: texto superpuesto evaluado O(n²) emitiendo un finding HIGH **por cada par** →
  una tabla densa dispara decenas de alertas y fuerza revisión sola.
- `agent.py`: todo indexado por `numero_factura` → dos archivos con el mismo número se pisan
  (y duplicados es caso de uso central). `final_confidence = 1.0` al rechazar; multiplicadores
  mágicos 0.70/0.80 sobre una confianza autoreportada por el LLM y no calibrada.
- `extraction.py` revienta en import sin `GEMINI_API_KEY` (bloquea tests); Tesseract con ruta
  Windows hardcodeada; Celery+Redis obligatorios incluso en local; no existe `tests/`.

### 1.4 Falta de novedad
Nada del pipeline es nuevo: extracción VLM es commodity, las reglas aritméticas son triviales,
ELA/copy-move/noise son técnicas 2000s-2010s cuya fragilidad ante recompresión está documentada.
Ya existen datasets de forgery documental (Find it! — recibos franceses; T-SROIE; DocTamper,
CVPR 2023) y detectores aprendidos SOTA (TruFor, CAT-Net, PSCC-Net) contra los que hoy no se
compara nada.

### 1.5 Lo que sí vale (conservar)
1. **Separación de autoridad**: solo el código determinista rechaza; LLM y forense solo derivan
   a humano. Arquitectura honesta y poco común.
2. **Filosofía de evidencia**: toda alerta con overlay visual + cita de procedencia.
3. **Postura de honestidad metodológica** declarada (limitaciones, archivo-vs-contenido).
   La ejecución no estuvo a la altura; la postura es el activo.

---

## 2. Tesis de investigación

> **Ningún detector forense individual sobrevive a las condiciones reales de transmisión de
> facturas (recompresión, WhatsApp, print-scan). Pero la fusión calibrada de señales débiles e
> independientes (píxel + estructura + tipografía + aritmética + semántica), con ruteo selectivo
> conformal, permite automatizar X% del volumen con una cota estadística demostrable de ≤Y% de
> fuga de fraude.**

Esto reordena el proyecto: la tabla actual de detectores mediocres pasa de vergüenza a punto de
partida del argumento.
- **Resultado 1** (parcial, ya insinuado): los módulos individuales fallan bajo condiciones reales.
- **Resultado 2** (la contribución): la fusión calibrada los vuelve útiles en agregado.
- **Resultado 3** (el titular): garantía conformal sobre el conjunto AUTO_APPROVE —
  "automatizamos el 60-70% del volumen con fuga ≤1% garantizada y evidencia auditable del resto".

**Threat model como sección de primera clase** (a redactar en Fase 4): qué adversario cubre cada
capa (casual con Photoshop / profesional que regenera el documento / fraude de contenido), qué
queda explícitamente fuera.

---

## 3. Pilares

### Pilar A — Benchmark realista (prerequisito y moat principal)
Generador de manipulaciones de adversario real, no parches aleatorios:
- **Edición de dígitos real**: localizar dígitos de importes vía OCR, reemplazar por dígitos
  renderizados con fuente/tamaño/color estimados del contexto (font-matching), con blending.
- **Inpainting**: borrar líneas de cargo con inpainting (cv2/LaMa; difusión opcional).
- **Splice** desde otro documento del corpus.
- **Cadenas de transmisión como dimensión experimental**: {original, recompresión JPEG aleatoria,
  simulación WhatsApp (resize + q≈70), print-scan simulado}. Reportar degradación por cadena.
- Fuentes: IDSEM (ancla española), `mychen76/invoices-and-receipts_ocr_v1`, FATURA.
- Escala: miles de muestras. Splits calibración/test estrictos, semillas fijas, máscaras GT,
  métrica de localización IoU obligatoria.
- **Publicar en HuggingFace Hub** con datasheet → artefacto citable y visibilidad.

### Pilar B — Baselines fuertes y comparación honesta
Sobre el benchmark: stack clásico de Cotejo + 1-2 detectores aprendidos preentrenados (TruFor
y/o CAT-Net, solo inferencia) + **VLM-como-forense** (Gemini: "¿está manipulada? ¿dónde?").
Tabla maestra: detector × tipo de ataque × cadena de transmisión, con APCER/BPCER/AUC/IoU.
La comparación clásico vs. aprendido vs. VLM en facturas bajo transmisión realista no existe
bien hecha.

### Pilar C — Fusión calibrada + ruteo conformal (la contribución técnica)
Reemplazar el scorer de pesos mágicos y los multiplicadores 0.70/0.80 por:
regresión logística/isotónica sobre scores de módulo + clase de documento + señales del motor
determinista → probabilidad calibrada de manipulación → **predicción conformal selectiva** para
el ruteo. Reportar curvas riesgo-cobertura.

### Moat comercial
1. **Dataset de calibración + metodología de ataque realista.** Replicar los detectores es
   trivial; replicar la evidencia de que funcionan, no. Feedback de revisión manual de cada
   cliente → flywheel de datos.
2. **La garantía como SLA**: "≤Y% de fuga al Z% de automatización, recalibrado mensualmente".
3. **Vertical regulatorio ES/LatAm**: Veri*factu/SII (España), CFDI (México); dominio (CUPS, CIF,
   estructura tarifaria); reportes de evidencia "court-ready" en español.
4. **No-moat** (no sobreinvertir): los detectores en sí, el prompt, la UI.

---

## 4. Fases de ejecución

### Fase 0 — Higiene científica (2-3 días) — EN EJECUCIÓN
Sin esto, todo lo demás hereda la contaminación.

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 0.1 | Congelar umbrales fuera del loop de eval: revertir tolerancia copy_move a spec (±2px, parametrizada en config), restaurar ratio_test/eps/min_samples de spec, documentar procedencia de cada valor en `config.yaml` | Ningún número mágico en código; config con comentarios de procedencia |
| 0.2 | Determinismo: eliminar ruido sin semilla en typography (regularización ridge de covarianza); semillas fijas en inyectores | Dos corridas sobre el mismo doc → findings idénticos |
| 0.3 | Arreglar `baseline_offset` (origin del span vs línea, no `line["dir"]`); severidad graduada en typography | Feature con varianza informativa; HIGH solo para desviaciones extremas |
| 0.4 | Unificar coordenadas: todo bbox en puntos PDF; `geometry.py` con conversiones e IoU compartido | Refuerzo cruzado y overlays operan en el mismo espacio |
| 0.5 | ELA: reactivar filtro de bordes; ELA y noise emiten bbox del componente anómalo | Findings localizables y elegibles para refuerzo cruzado |
| 0.6 | metadata: deduplicar texto superpuesto (un finding por página con conteo) | Documentos densos no inflan el riesgo |
| 0.7 | `agent.py` indexado por archivo; `extraction.py` con cliente lazy; Celery opcional (sync local); Tesseract por env/which | Pipeline corre local sin Redis ni API key (forense), tests importables |
| 0.8 | Suite de tests + CI (GitHub Actions) | `pytest` verde local y en CI |
| 0.9 | Reescribir eval: hit = IoU ≥ 0.2 contra máscara GT (coords normalizadas), split calib/test determinista, modo replay local sobre `data/hf_eval` | Métricas honestas reproducibles offline |
| 0.10 | Correr el eval reparado y registrar el **baseline honesto** en este documento, aunque sea peor | Tabla de resultados Fase 0 abajo |

**Nota:** los inyectores siguen siendo irreales en Fase 0 (eso es Fase 1). El baseline honesto de
Fase 0 mide los detectores reparados contra los ataques sintéticos viejos pero con scoring
correcto. Sirve como punto de comparación interno, no como afirmación pública.

### Fase 1 — Benchmark realista (1-2 semanas)
Generador (dígitos font-matched, inpainting, splice) × cadenas de transmisión × 3 fuentes.
Miles de muestras con máscaras. Datasheet. Publicación en HF Hub.
*Aceptación:* dataset publicado; distribución de ataques auditada manualmente (muestreo de 50);
ningún ataque "indetectable por principio" (parche invisible) en el set.

### Fase 2 — Baselines aprendidos (1 semana) — PRIORIDAD ELEVADA tras Fase 1
El stack clásico no localiza nada (Fase 1, §5); sin un detector que localice no hay
contribución de localización que fusionar. Por eso esta fase deja de ser comparación
"nice-to-have" y pasa a ser la pieza que decide si el proyecto tiene un resultado positivo.
- **TruFor y/o CAT-Net en inferencia** (pesos preentrenados, sin entrenar nada) sobre el
  benchmark v1. Producen un mapa de manipulación → bbox por umbral → misma métrica IoU.
- **VLM-as-judge** (Gemini: "¿manipulada? ¿dónde?") como tercer punto de comparación.
*Aceptación:* tabla maestra detector × ataque × cadena con APCER página/localizado y BPCER,
calib/test separados. Decisión explícita: ¿hay AL MENOS un detector con APCER localizado
< 50% en alguna celda? Si sí, hay localización que vale la pena fusionar; si no, el proyecto
pivota a "auditoría a nivel documento con garantías" y la localización se declara problema
abierto (resultado honesto igualmente publicable).

### Fase 3 — Fusión calibrada + ruteo conformal (1 semana)
Combinador calibrado (logística + isotónica), curvas riesgo-cobertura, garantía conformal sobre
AUTO_APPROVE. Sustituye umbrales mágicos del ruteo.
*Aceptación:* "X% de automatización con fuga ≤Y% (90% confianza)" medido en test split;
el scorer YAML de pesos queda deprecado.

### Fase 4 — Escritura y producto (continuo)
README reescrito como paper corto (motivación → threat model → benchmark → resultados →
limitaciones), candidato a arXiv. Demo con el informe de evidencia como protagonista.
Medir O1 pendiente (exactitud de extracción contra IDSEM).
*Aceptación:* un revisor externo puede reproducir la tabla principal con un comando.

---

## 5. Registro de resultados

### Fase 0 — Baseline honesto (ejecutado 2026-06-11)

Corrida: `python eval/eval_huggingface.py --local_dir data/hf_eval --split {calib|test}`
(41 documentos reales de HF, inyectores antiguos, detectores reparados, umbrales de spec,
scoring con localización IoU≥0.2 contra máscara GT). Crudos en `data/eval_calib.json` y
`data/eval_test.json`.

**Split test (lo reportable):**

| Módulo | Ataque objetivo | APCER pág. | APCER loc. (IoU≥0.2) | BPCER | n (pos/neg) |
|---|---|---|---|---|---|
| typography | digit_swap | 25% | **100%** | **70%** | 20/20 |
| ela_noise | region_patch | 30% | **100%** | **70%** | 20/20 |
| copy_move | clone | **100%** | 100% | 0% | 20/20 |

*(Split calib, consistente: typography 40/100/60; ela_noise 20/100/80; copy_move 100/100/0.)*

**Lectura honesta:**
1. **Ningún módulo localiza ninguna manipulación** (APCER localizado = 100% en todos).
   Los "hits" a nivel página de typography y ela_noise coexisten con BPCER de 60-80%:
   son estadísticamente indistinguibles de falsas alarmas que caen por azar en una página
   manipulada. La tabla anterior del README (typography 50/45, ELA "0/100") era un
   artefacto del scoring a nivel página.
2. **copy_move con umbrales de spec (coherencia ±2px) no detecta nada**: la recompresión
   JPEG de los ataques rompe la coherencia rígida de keypoints. Su BPCER de 0% no es
   mérito, es silencio total.
3. **Caveat del inyector**: el APCER localizado de 100% también refleja que los ataques
   antiguos son inválidos (bloques aleatorios en posiciones aleatorias, a menudo
   fondo-sobre-fondo). Este baseline NO mide la capacidad máxima de los detectores;
   mide que con esta suite de ataques no se puede afirmar nada. Exactamente lo que
   motiva el benchmark realista de Fase 1.

**Conclusión de Fase 0:** el estado real del stack forense clásico sobre imágenes
recomprimidas es "sin evidencia de capacidad de detección localizada". Punto de partida
limpio para la tesis (powerUp.md §2): los detectores individuales fallan; el valor habrá
que construirlo en la fusión calibrada y demostrarlo sobre ataques realistas.

### Fase 1 — Benchmark realista v1 + baseline del stack clásico (ejecutado 2026-06-11)

**Benchmark generado** (`data/benchmark_v1`, manifest de 960 muestras):
41 documentos reales × {5 ataques realistas + limpio} × {none, recompress, whatsapp,
print_scan}. Ataques guiados por OCR sobre contenido real (no bloques aleatorios), con
máscara GT exacta. Scripts: `eval/realistic_injector.py`, `eval/transmission.py`,
`eval/build_benchmark.py`, `eval/eval_benchmark.py`. Hallazgos crudos cacheados en
`findings_all.jsonl` (los reutiliza la Fase 3).

**Resultado del stack clásico — split test** (APCER: % de ataques NO detectados; menor mejor):

APCER **localizado** (IoU≥0.2 contra la máscara) — *el módulo señala la región real*:

| ataque (módulo objetivo) | none | recompress | whatsapp | print_scan |
|---|---|---|---|---|
| copy_move_region (copy_move) | 100 | 100 | 100 | 100 |
| digit_copy (copy_move) | 100 | 100 | 100 | 100 |
| digit_render (typography) | 100 | 100 | 100 | 100 |
| inpaint_erase (ela_noise) | 100 | 100 | 100 | 100 |
| splice_foreign (ela_noise) | 100 | 100 | 100 | 100 |

APCER **a nivel página** — *el módulo dispara en algún lugar de la página*:

| ataque | none | recompress | whatsapp | print_scan |
|---|---|---|---|---|
| copy_move_region | 100 | 100 | 100 | 100 |
| digit_copy | 100 | 100 | 100 | 100 |
| digit_render | 30 | 30 | 35 | 20 |
| inpaint_erase | 30 | 30 | 100 | 40 |
| splice_foreign | 30 | 30 | 95 | 30 |

BPCER (falsas alarmas en limpios, % — menor mejor):

| módulo | none | recompress | whatsapp | print_scan |
|---|---|---|---|---|
| typography | 70 | 75 | 55 | 75 |
| ela_noise | 70 | 70 | 0 | 75 |
| copy_move | 0 | 0 | 0 | 0 |

(Split calib consistente: localizado 100% en todo; mismas tendencias de página y BPCER.)

**Lectura — los tres hechos honestos:**
1. **Localización ≈ 0 en todo el espacio.** Ningún módulo señala la región manipulada de
   ningún ataque bajo ninguna cadena (APCER localizado = 100% uniforme). La capa forense
   clásica no localiza fraude en facturas reales.
2. **Las "detecciones" de página son indistinguibles de ruido.** typography y ela_noise
   disparan en ~70% de las páginas manipuladas (APCER página ~30%) pero también en
   55-80% de las limpias (BPCER). Es decir: cuando aciertan la página es casi por la misma
   tasa con que se equivocan en una limpia, y nunca sobre la región correcta. No hay señal
   utilizable, hay una moneda sesgada.
3. **La transmisión rompe los detectores de dos formas opuestas.** WhatsApp (downscale+q70)
   apaga ela_noise (BPCER 0% pero APCER página salta a 95-100%: silencio total); las demás
   cadenas lo dejan disparando en todas partes. copy_move con coherencia ±2px es silencio
   absoluto en todo el grid (0 detección / 0 FP): la recompresión JPEG destruye la
   coherencia rígida de keypoints.

**Caveat metodológico:** las máscaras de digit_copy/digit_render son pequeñas (un dígito),
lo que endurece IoU≥0.2; pero el APCER de página y el BPCER (independientes de la máscara)
confirman la conclusión sin depender del umbral de localización.

**Implicación para Fases 2-3:** la fusión de estas señales NO puede recuperar localización
(no hay localización que fusionar). Dos consecuencias que redirigen el plan:
- **Pilar B (baselines aprendidos) sube de prioridad:** sin un detector que localice (TruFor/
  CAT-Net en inferencia, o VLM-as-judge), la contribución de localización no existe. Es la
  próxima pieza crítica, no opcional.
- **Pilar C (fusión + conformal) se reencuadra a nivel documento:** el valor demostrable del
  stack clásico, si lo hay, es como señal débil de "derivar a humano" a nivel página, no como
  localizador. La garantía conformal se medirá sobre la decisión de ruteo, no sobre el píxel.

Este es el **Resultado 1** de la tesis (powerUp.md §2), ahora medido sobre ataques realistas
y cadenas de transmisión, no insinuado: *ningún detector forense clásico individual sobrevive
a las condiciones reales de transmisión de facturas.*

### Fase 2 — Baseline VLM-as-judge (parcial, bloqueado por cuota — 2026-06-11)

**Construido:** `eval/vlm_judge.py` (Gemini como perito forense: salida JSON con
`tampered` + bboxes normalizados, normalizada al mismo contrato que los detectores
clásicos) y `eval/eval_vlm.py` (barrido cacheado/resume-able, misma métrica IoU/APCER/BPCER,
con corte temprano y exclusión de errores de las métricas).

**Resultado parcial (n=3 por celda, solo cadena `none` — el smoke antes de agotar cuota):**

| | localizado | página | BPCER |
|---|---|---|---|
| VLM-judge (flash) | APCER 100% | APCER 33–67% | **0%** |

Señal preliminar (a confirmar a escala): el VLM **tampoco localiza** la región editada
(razona sobre el total aritmético, no sobre el píxel), PERO a nivel documento marca
manipulación con **BPCER ≈ 0%**, frente al 55–75% del stack clásico. Operating point
opuesto y potencialmente útil para "derivar a humano".

**BLOQUEO:** la API key de Gemini está en **free tier = 20 requests/día/modelo**
(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, quotaValue 20). El smoke consumió la
cuota diaria; el barrido completo (480 test) es inviable sin habilitar facturación. El caché
quedó depurado de los 207 errores 429 (solo 19 veredictos válidos conservados). Decisión de
producto pendiente con el usuario: habilitar billing / reducir alcance / diferir VLM.

### Decisiones tomadas durante la ejecución

- 2026-06-11: el cambio sin commitear en `copy_move.py` (tolerancia ±2→±8px) se revierte; la
  tolerancia pasa a `config.yaml` con el valor del spec (±2px). Cualquier recalibración futura
  ocurrirá sobre el split de calibración de Fase 1, nunca sobre el set de reporte.
- 2026-06-11: regla de "fuente anómala" en metadata recibe guarda de mínimo de spans
  (`min_spans_for_font_rule: 5`): con pocos spans toda fuente es "única" (FP estructural
  detectado por la suite de tests, no por ajuste de métrica).
- 2026-06-11: `eval/eval_forensics.py` queda marcado LEGADO (scoring a nivel página sin
  máscaras); la fuente de verdad es `eval/eval_huggingface.py`.
- 2026-06-11: Fase 0 cerrada. La tabla de métricas forenses del README se reemplaza por el
  baseline honesto con localización (ver §5) y la nota de que los números previos quedan
  retirados por metodología inválida.
