# Datasheet — Cotejo Invoice Tamper Benchmark v1

Sigue la estructura de *Datasheets for Datasets* (Gebru et al., 2021). Describe el benchmark
sintético-realista de manipulación de facturas usado para evaluar la capa forense de Cotejo
(powerUp.md, Fase 1). Pensado para acompañar una publicación en HuggingFace Hub.

---

## Motivación

- **¿Para qué se creó?** Para medir, de forma honesta y reproducible, si los detectores
  forenses (clásicos, aprendidos o VLM) localizan/detectan manipulación de facturas **bajo las
  condiciones reales de transmisión** (recompresión, WhatsApp, print-scan). Los benchmarks
  previos del proyecto contaban como detección cualquier alerta a nivel página, con ataques
  irreales y sin split — produciendo métricas no interpretables (ver powerUp.md §1.2).
- **Hueco que llena:** no existe un benchmark público de forgery en facturas que cruce
  *tipo de ataque × canal de transmisión* con máscaras de localización y splits limpios.

## Composición

- **Instancia:** una imagen de factura (manipulada o limpia) sometida a una cadena de
  transmisión, con su etiqueta y (si aplica) máscara binaria de la región alterada.
- **Tamaño:** 960 muestras = 41 documentos base × {5 ataques + 1 limpio} × 4 cadenas. 800
  máscaras de ground-truth (las muestras limpias no tienen máscara).
- **Documentos base:** 41 facturas/recibos reales de `mychen76/invoices-and-receipts_ocr_v1`
  (HuggingFace), guardados como JPEG de alta calidad.
- **Ataques (guiados por OCR, sobre contenido real — nunca fondo aleatorio):**
  - `digit_copy` — copia un dígito de un importe sobre otro del mismo doc (font-matched).
  - `digit_render` — reescribe un dígito con una fuente externa (color/tamaño estimados).
  - `inpaint_erase` — borra un importe con inpainting (Telea).
  - `splice_foreign` — pega un token numérico de OTRO documento del corpus.
  - `copy_move_region` — clona una banda de texto sobre otra zona (translación rígida).
- **Cadenas de transmisión:** `none`, `recompress` (JPEG q60–85), `whatsapp` (≤1280px + q70),
  `print_scan` (rotación, blur, ruido de sensor). Las operaciones geométricas se aplican
  idénticamente a la máscara.
- **Etiquetas:** `label ∈ {clean, tampered}`, `attack`, `chain`, `target_module` (qué módulo
  forense debería detectarlo), `split`, ruta de imagen y máscara. En `manifest.jsonl`.
- **Splits:** `calib` (documentos de índice par) / `test` (impar), separados **por documento**
  para que ninguna variante del mismo doc cruce el split.

## Proceso de generación

- Generado por `eval/build_benchmark.py` a partir de `eval/realistic_injector.py` (ataques) y
  `eval/transmission.py` (cadenas). Todo con **RNG semillado** (`bench-{doc}-{attack}-{chain}`):
  el dataset es bit-reproducible.
- OCR (Tesseract) localiza los tokens numéricos sobre los que caen los ataques.

## Preprocesamiento / limpieza

- Imágenes base normalizadas a JPEG q95. Ningún ataque "indetectable por principio" (no hay
  parches sobre fondo blanco vacío): cada ataque se ancla a un token real detectado por OCR.

## Usos

- **Pensado para:** evaluar detección/localización de manipulación con métricas APCER (página y
  localizada con IoU≥0.2), BPCER, y como fuente de features para fusión calibrada + ruteo
  conformal (`eval/eval_benchmark.py`, `eval/fusion_routing.py`).
- **No usar para:** afirmar generalización a fraude de campo real. Las manipulaciones son
  sintéticas (aunque realistas); ver THREAT_MODEL.md para la taxonomía de adversarios cubiertos
  y los vectores fuera de alcance (fabricación de contenido, adversario adaptativo).
- **Sesgo conocido:** prevalencia de manipulación saturada (83%) a propósito; los titulares de
  automatización/fuga deben reproyectarse a la prevalencia real de despliegue (<5%).

## Distribución y mantenimiento

- **Imágenes:** no se versionan en git por tamaño (~regenerables). Se regeneran con
  `python eval/build_benchmark.py` (determinista). Candidato a publicación en HF Hub.
- **Crudos de evaluación versionados:** `metrics_*.json` (clásico), `vlm_metrics_*.json`,
  `findings_all.jsonl` (hallazgos por muestra, reutilizados por la fusión).
- **Licencia de los documentos base:** heredada de `mychen76/invoices-and-receipts_ocr_v1`
  (verificar términos del dataset fuente antes de redistribuir imágenes).
- **Versión:** v1 (2026-06). Cambios futuros (más docs, ataques con difusión/LaMa, detectores
  aprendidos) → v2 con changelog.
